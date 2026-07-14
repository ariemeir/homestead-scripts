#!/usr/bin/env python3
"""3D scanner turntable session controller ("shika").

Runs a complete turntable photogrammetry session against ScannerCam on saru
and the Arduino IR turntable. See the MVP spec and capture/protocols/api_v1.md.

Usage:
    ./scan.py run --name red_mug --degrees 10
    ./scan.py preflight --name red_mug --degrees 5
    ./scan.py resume scans/incoming/<session_id>
    ./scan.py package scans/incoming/<session_id>
    ./scan.py test-camera
    ./scan.py test-turntable
    ./scan.py cleanup <project_id>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Re-exec under the project virtualenv (PyYAML/pyserial live there) so the
# script "just works" when invoked as ./scan.py with a bare system python.
_VENV_PY = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

# Make sibling packages (controller/, camera/, turntable/) importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse

from camera.scannercam import ScannerCamClient
from controller.config import Config
from controller.errors import EXIT_SUCCESS, ConfigError, ScanError
from controller.models import CapturePlan, make_session_id
from controller.session import SessionController
from controller.state import ControllerLock, SessionLayout, StateStore
from turntable import build_turntable


def _build_camera(config: Config, require_token: bool = True) -> ScannerCamClient:
    return ScannerCamClient(
        base_url=config.camera.base_url,
        token=config.token(required=require_token),
        connect_timeout=config.camera.connect_timeout_seconds,
        capture_timeout=config.camera.capture_timeout_seconds,
        download_timeout=config.camera.download_timeout_seconds,
    )


def _controller_for(config: Config, layout: SessionLayout, args, session_id, display_name):
    plan = CapturePlan.from_step(
        config.capture.degrees_per_frame, config.capture.settle_seconds
    )
    interactive = not getattr(args, "yes", False)
    camera = _build_camera(config)
    turntable = build_turntable(
        config, getattr(args, "turntable", None), interactive=interactive
    )
    store = StateStore(layout)
    lock = ControllerLock(config.session.scans_root.parent / ".controller.lock", session_id)
    return SessionController(
        config=config,
        session_id=session_id,
        display_name=display_name,
        plan=plan,
        camera=camera,
        turntable=turntable,
        layout=layout,
        store=store,
        lock=lock,
        require_locks=config.camera.require_locks,
        assume_yes=getattr(args, "yes", False),
        interactive=interactive,
    ), turntable, lock


def _apply_overrides(config: Config, args) -> None:
    if getattr(args, "degrees", None) is not None:
        _validate_step(args.degrees)
        config.capture.degrees_per_frame = float(args.degrees)
    if getattr(args, "settle_seconds", None) is not None:
        config.capture.settle_seconds = float(args.settle_seconds)


def _validate_step(degrees: float) -> None:
    if degrees <= 0 or degrees > 360:
        raise ConfigError("--degrees must be > 0 and <= 360.")
    count = round(360.0 / degrees)
    if abs(count * degrees - 360.0) > 1e-6:
        raise ConfigError("--degrees must divide evenly into 360 for the MVP.")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_run(config: Config, args) -> int:
    _apply_overrides(config, args)
    session_id = make_session_id(args.name)
    layout = SessionLayout(config.session.scans_root / session_id)
    if layout.root.exists():
        raise ConfigError(f"Session directory already exists: {layout.root}")
    layout.create_skeleton()

    controller, turntable, lock = _controller_for(config, layout, args, session_id, args.name)
    controller.init_state()
    try:
        with lock:
            return controller.run()
    finally:
        turntable.close()


def cmd_preflight(config: Config, args) -> int:
    _apply_overrides(config, args)
    session_id = make_session_id(args.name)
    layout = SessionLayout(config.session.scans_root / session_id)
    layout.create_skeleton()
    controller, turntable, lock = _controller_for(config, layout, args, session_id, args.name)
    controller.init_state()
    try:
        with lock:
            controller.print_header()
            controller.write_session_manifest()
            controller.snapshot_config()
            controller.preflight()
        print("Preflight passed.")
        return EXIT_SUCCESS
    finally:
        turntable.close()


def cmd_resume(config: Config, args) -> int:
    root = Path(args.session_dir).resolve()
    if not (root / "session.json").exists():
        raise ConfigError(f"Not a session directory (no session.json): {root}")
    layout = SessionLayout(root)
    store = StateStore(layout)
    manifest = store.load_session_manifest()
    session_id = manifest["session_id"]
    display_name = manifest.get("display_name", session_id)
    cplan = manifest["capture_plan"]
    plan = CapturePlan(
        degrees_per_frame=cplan["degrees_per_frame"],
        frame_count=cplan["frame_count"],
        first_angle_degrees=cplan["first_angle_degrees"],
        last_angle_degrees=cplan["last_angle_degrees"],
        settle_seconds=cplan["settle_seconds"],
    )
    config.capture.degrees_per_frame = plan.degrees_per_frame
    config.capture.settle_seconds = plan.settle_seconds

    interactive = not getattr(args, "yes", False)
    camera = _build_camera(config)
    turntable = build_turntable(config, getattr(args, "turntable", None), interactive=interactive)
    lock = ControllerLock(config.session.scans_root.parent / ".controller.lock", session_id)
    controller = SessionController(
        config=config,
        session_id=session_id,
        display_name=display_name,
        plan=plan,
        camera=camera,
        turntable=turntable,
        layout=layout,
        store=store,
        lock=lock,
        require_locks=config.camera.require_locks,
        assume_yes=getattr(args, "yes", False),
        interactive=interactive,
    )
    try:
        with lock:
            return controller.resume()
    finally:
        turntable.close()


def cmd_package(config: Config, args) -> int:
    root = Path(args.session_dir).resolve()
    if not (root / "session.json").exists():
        raise ConfigError(f"Not a session directory (no session.json): {root}")
    layout = SessionLayout(root)
    store = StateStore(layout)
    manifest = store.load_session_manifest()
    session_id = manifest["session_id"]
    cplan = manifest["capture_plan"]
    plan = CapturePlan(
        degrees_per_frame=cplan["degrees_per_frame"],
        frame_count=cplan["frame_count"],
        first_angle_degrees=cplan["first_angle_degrees"],
        last_angle_degrees=cplan["last_angle_degrees"],
        settle_seconds=cplan["settle_seconds"],
    )
    camera = _build_camera(config, require_token=False)
    turntable = build_turntable(config, "noop", interactive=False)
    lock = ControllerLock(config.session.scans_root.parent / ".controller.lock", session_id)
    controller = SessionController(
        config=config,
        session_id=session_id,
        display_name=manifest.get("display_name", session_id),
        plan=plan,
        camera=camera,
        turntable=turntable,
        layout=layout,
        store=store,
        lock=lock,
        require_locks=config.camera.require_locks,
        assume_yes=True,
        interactive=False,
    )
    controller.load_existing()
    return controller.finalize()


def cmd_test_camera(config: Config, args) -> int:
    camera = _build_camera(config)
    print(f"ScannerCam: {camera.base_url}")
    health = camera.health()
    print(f"  health:  {health.get('status')} (v{health.get('version')})")
    status = camera.status()
    cam = status.get("camera", {})
    print(f"  camera:  authorized={cam.get('authorized')} "
          f"session_running={cam.get('session_running')} "
          f"capture_in_progress={status.get('capture_in_progress')}")
    for key in ("focus", "exposure", "white_balance"):
        print(f"    {key}: {(cam.get(key) or {}).get('mode')}")
    storage = status.get("storage", {})
    free = storage.get("free_bytes")
    print(f"  storage: {free // 1_000_000 if free else '?'} MB free, "
          f"{storage.get('image_count')} images")
    print("Camera OK.")
    return EXIT_SUCCESS


def cmd_test_turntable(config: Config, args) -> int:
    turntable = build_turntable(config, getattr(args, "turntable", None), interactive=True)
    print(f"Turntable driver: {turntable.describe()}")
    turntable.connect()
    if not getattr(args, "yes", False):
        answer = input(
            "This will send ONE start toggle, wait ~1s, then ONE stop toggle.\n"
            "Make sure the table is armed (continuous, CW) and clear. Continue? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return EXIT_SUCCESS
    try:
        print("  start toggle...")
        turntable.toggle()
        import time

        time.sleep(1.0)
        print("  stop toggle...")
        turntable.toggle()
        print("Turntable test OK (sent two toggles).")
        return EXIT_SUCCESS
    finally:
        turntable.close()


def cmd_cleanup(config: Config, args) -> int:
    camera = _build_camera(config)
    project_id = args.project_id
    if not getattr(args, "yes", False):
        answer = input(f"Delete remote ScannerCam project {project_id!r}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return EXIT_SUCCESS
    camera.delete_project(project_id)
    print(f"Deleted remote project {project_id}.")
    return EXIT_SUCCESS


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # --config is shared by every subcommand (parsed after the subcommand name).
    common_config = argparse.ArgumentParser(add_help=False)
    common_config.add_argument(
        "--config", type=Path, default=None, help="Path to scanner.yaml"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def new_sub(name, **kw):
        return sub.add_parser(name, parents=[common_config], **kw)

    def add_common(p):
        p.add_argument("--turntable", choices=["arduino_ir", "noop"], default=None)
        p.add_argument("--yes", action="store_true", help="Skip confirmations (unattended).")

    p_run = new_sub("run", help="Run a full scan session.")
    p_run.add_argument("--name", required=True)
    p_run.add_argument("--degrees", type=float, default=None)
    p_run.add_argument("--settle-seconds", type=float, default=None, dest="settle_seconds")
    add_common(p_run)
    p_run.set_defaults(func=cmd_run)

    p_pre = new_sub("preflight", help="Run preflight checks only.")
    p_pre.add_argument("--name", required=True)
    p_pre.add_argument("--degrees", type=float, default=None)
    p_pre.add_argument("--settle-seconds", type=float, default=None, dest="settle_seconds")
    add_common(p_pre)
    p_pre.set_defaults(func=cmd_preflight)

    p_res = new_sub("resume", help="Resume an interrupted session.")
    p_res.add_argument("session_dir")
    add_common(p_res)
    p_res.set_defaults(func=cmd_resume)

    p_pkg = new_sub("package", help="Validate and package a session.")
    p_pkg.add_argument("session_dir")
    p_pkg.set_defaults(func=cmd_package)

    p_cam = new_sub("test-camera", help="Probe ScannerCam.")
    p_cam.set_defaults(func=cmd_test_camera)

    p_tt = new_sub("test-turntable", help="Send one start + one stop toggle.")
    add_common(p_tt)
    p_tt.set_defaults(func=cmd_test_turntable)

    p_clean = new_sub("cleanup", help="Delete a remote ScannerCam project.")
    p_clean.add_argument("project_id")
    p_clean.add_argument("--yes", action="store_true")
    p_clean.set_defaults(func=cmd_cleanup)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        config = Config.load(args.config)
        return args.func(config, args)
    except ScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 8


if __name__ == "__main__":
    raise SystemExit(main())

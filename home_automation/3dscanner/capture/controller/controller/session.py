"""Session orchestration: preflight, the capture loop, finalize, and resume.

This is the "shika" side of the rig. It drives the turntable through the
assumed-state safety machine (spec §4), captures/downloads/verifies each frame
before the next move (spec §14/§15), and never auto-recovers from an unknown
turntable state (spec §19).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Callable

from camera.scannercam import ScannerCamClient
from turntable.base import TurntableController

from . import package as pkg
from .config import Config
from .errors import (
    CameraError,
    PackagingError,
    PreflightError,
    ScanError,
    TurntableStateUnknown,
    VerificationError,
)
from .models import (
    SCHEMA_VERSION,
    AssumedState,
    CapturePlan,
    FrameRecord,
    Status,
    now_iso,
)
from .state import ControllerLock, SessionLayout, StateStore, atomic_write_json

_MIN_FREE_BYTES = 500 * 1024 * 1024  # floor for the free-space preflight check
_EST_BYTES_PER_FRAME = 5 * 1024 * 1024


class SessionController:
    def __init__(
        self,
        config: Config,
        session_id: str,
        display_name: str,
        plan: CapturePlan,
        camera: ScannerCamClient,
        turntable: TurntableController,
        layout: SessionLayout,
        store: StateStore,
        lock: ControllerLock,
        *,
        require_locks: bool = True,
        assume_yes: bool = False,
        interactive: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        prompt: Callable[[str], str] = input,
    ):
        self.config = config
        self.session_id = session_id
        self.display_name = display_name
        self.plan = plan
        self.camera = camera
        self.turntable = turntable
        self.layout = layout
        self.store = store
        self.lock = lock
        self.require_locks = require_locks
        self.assume_yes = assume_yes
        self.interactive = interactive
        self._sleep = sleep
        self._prompt = prompt
        self.frames: list[FrameRecord] = []
        self._camera_locked = require_locks

    # ==================================================================== #
    # Console helpers
    # ==================================================================== #
    @staticmethod
    def _line(label: str, status: str = "OK") -> None:
        dots = "." * max(3, 34 - len(label))
        print(f"  {label}{dots} {status}")

    def print_header(self) -> None:
        rule = "─" * 40
        print("3D Scanner Session")
        print(rule)
        print(f"Session:       {self.session_id}")
        print(f"Camera:        {self.camera.base_url}")
        print(f"Turntable:     {self.turntable.describe()}")
        print(f"Angular step:  {self.plan.degrees_per_frame:g}°")
        print(f"Frames:        {self.plan.frame_count}")
        print(f"Settle time:   {self.plan.settle_seconds:g} seconds")
        print(rule)
        print()

    # ==================================================================== #
    # Manifest / state bootstrap
    # ==================================================================== #
    def write_session_manifest(self) -> None:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "project_id": self.session_id,
            "display_name": self.display_name,
            "created_at": now_iso(),
            "capture_plan": self.plan.to_dict(),
            "camera": {
                "base_url": self.camera.base_url,
                "require_locks": self.require_locks,
            },
            "turntable": {
                "driver": self.turntable.driver,
                "control_type": self.turntable.control_type,
                "interface_directory": _as_str(self.config.turntable.interface_directory),
                "degrees_per_second": self.config.degrees_per_second(),
            },
        }
        self.store.write_session_manifest(manifest)

    def init_state(self, status: str = Status.INITIALIZING) -> None:
        self.store.init_state(
            session_id=self.session_id,
            status=status,
            current_frame=0,
            last_completed_frame=-1,
            next_intended_angle_degrees=0.0,
            turntable_assumed_state=self.turntable.assumed_state,
            frames_completed=0,
            remote_images_confirmed=0,
            local_images_verified=0,
            last_error=None,
        )

    def snapshot_config(self) -> None:
        try:
            self.layout.config_snapshot.write_text(
                self.config.source_path.read_text()
            )
        except OSError:
            pass

    # ==================================================================== #
    # Preflight (spec §13)
    # ==================================================================== #
    def preflight(self) -> None:
        self.store.update_state(status=Status.PREFLIGHT)
        print("Preflight")
        self._preflight_local()
        self._preflight_camera()
        self._preflight_turntable()
        self._confirm_user()
        self.store.update_state(status=Status.READY)
        print()

    def _preflight_local(self) -> None:
        if abs(round(360.0 / self.plan.degrees_per_frame) * self.plan.degrees_per_frame - 360.0) > 1e-6:
            raise PreflightError("Step must divide evenly into 360° for the MVP.")
        self.config.token(required=True)  # raises ConfigError if missing
        needed = max(_MIN_FREE_BYTES, self.plan.frame_count * _EST_BYTES_PER_FRAME)
        import shutil

        free = shutil.disk_usage(self.layout.root.parent).free
        if free < needed:
            raise PreflightError(
                f"Insufficient local disk: {free // 1_000_000} MB free, "
                f"need ~{needed // 1_000_000} MB."
            )
        self._line("local checks")

    def _preflight_camera(self) -> None:
        try:
            health = self.camera.health()
        except CameraError as exc:
            raise PreflightError(f"ScannerCam health check failed: {exc}") from exc
        if health.get("status") not in ("ok", "degraded"):
            raise PreflightError(f"ScannerCam health returned: {health.get('status')}")

        status = self.camera.status()
        atomic_write_json(self.layout.metadata / "camera_status_start.json", status)

        cam = status.get("camera", {})
        if not cam.get("authorized"):
            raise PreflightError("Camera is not authorized on saru.")
        if not cam.get("session_running"):
            raise PreflightError("ScannerCam capture session is not running.")
        if status.get("capture_in_progress"):
            raise PreflightError("A capture is already in progress on ScannerCam.")

        if self.require_locks:
            self._check_locks(cam)

        storage = status.get("storage", {})
        free = storage.get("free_bytes")
        if free is not None and free < _MIN_FREE_BYTES:
            raise PreflightError(
                f"Insufficient iPhone storage: {free // 1_000_000} MB free."
            )
        self._line("camera reachable")

    def _check_locks(self, cam: dict) -> None:
        for key in ("focus", "exposure", "white_balance"):
            mode = (cam.get(key) or {}).get("mode")
            if mode != "locked":
                raise PreflightError(
                    f"Camera {key.replace('_', ' ')} is not locked (mode={mode!r}). "
                    "Enable the locks in ScannerCam before scanning."
                )
        self._camera_locked = True
        self._line("camera locks active")

    def _preflight_turntable(self) -> None:
        try:
            self.turntable.connect()
        except ScanError:
            raise
        except Exception as exc:  # defensive: unexpected driver failure
            raise PreflightError(f"Turntable preflight failed: {exc}") from exc
        self._line(f"turntable ready ({self.turntable.driver})")

    def _confirm_user(self) -> None:
        if self.assume_yes:
            return
        print()
        print("Confirm:")
        for item in (
            "turntable is powered on",
            "turntable is stopped",
            "turntable is armed: continuous, clockwise, at your chosen speed",
            "object is aligned to 0° and centered",
            "phone is fixed; ScannerCam is open in the foreground",
            "camera locks are enabled",
        ):
            print(f"  - {item}")
        answer = self._prompt("Continue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            raise PreflightError("Aborted by user at preflight confirmation.")

    # ==================================================================== #
    # Movement (spec §14, §17, §18)
    # ==================================================================== #
    def _move(self, frame: int, from_angle: float, to_angle: float) -> None:
        step = self.plan.degrees_per_frame
        run_seconds = self.config.run_seconds_for(step)
        self.store.update_state(
            status=Status.MOVING,
            current_frame=frame,
            next_intended_angle_degrees=to_angle,
            turntable_assumed_state=AssumedState.RUNNING,
        )
        toggle_driven = self.turntable.control_type == "single_toggle_start_stop"
        if toggle_driven:
            self._line("sending start toggle")
        result = self.turntable.move_by_degrees(step, run_seconds)
        self.store.update_state(turntable_assumed_state=self.turntable.assumed_state)
        if toggle_driven:
            self._line(f"rotating for {run_seconds:.3f} seconds")
            self._line("sending stop toggle")
        else:
            self._line(f"manual rotation by {step:g}°")

        # Settle (spec §14).
        self.store.update_state(status=Status.SETTLING)
        self._sleep(self.plan.settle_seconds)
        result.settle_completed_at = now_iso()
        self._line(f"settling for {self.plan.settle_seconds:g} seconds")

        self.store.append_timing(
            frame=frame,
            from_angle=from_angle,
            to_angle=to_angle,
            requested_step=step,
            run_seconds=run_seconds,
            start_ts=result.start_toggle_sent_at,
            stop_ts=result.stop_toggle_sent_at,
            settle_ts=result.settle_completed_at,
        )

    # ==================================================================== #
    # Capture + download + verify (spec §15, §16, §20)
    # ==================================================================== #
    def _request_id(self, frame: int) -> str:
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"scannercam:{self.session_id}:frame:{frame}",
            )
        )

    def capture_and_pull(self, frame: int, angle: float) -> None:
        request_id = self._request_id(frame)
        meta = self._ensure_captured(frame, angle, request_id)
        self._line("capturing")
        self._download_and_verify(frame, meta)
        self._line("downloading")
        self._line("verifying SHA-256")
        self._record_frame(frame, angle, meta)

    def _ensure_captured(self, frame: int, angle: float, request_id: str) -> dict:
        cap = self.config.capture
        last_exc: CameraError | None = None
        for attempt in range(1, cap.max_capture_attempts + 1):
            self.store.update_state(
                status=Status.CAPTURING,
                current_frame=frame,
                next_intended_angle_degrees=angle,
            )
            try:
                return self.camera.capture(
                    project_id=self.session_id,
                    frame=frame,
                    angle_degrees=angle,
                    request_id=request_id,
                    require_locks=self.require_locks,
                    overwrite=False,
                )
            except CameraError as exc:
                last_exc = exc
                if exc.code == "frame_exists":
                    # A prior run already captured it — reuse the remote copy.
                    existing = self._remote_frame_metadata(frame)
                    if existing:
                        return existing
                if not exc.retryable or attempt == cap.max_capture_attempts:
                    self._record_error("capture", frame, exc, fatal=True)
                    raise
                self._record_error("capture", frame, exc, attempt=attempt)
                # Ambiguous failure: the capture may actually have landed.
                existing = self._remote_frame_metadata(frame, silent=True)
                if existing:
                    return existing
                self._sleep(cap.retry_delay_seconds * attempt)
        raise last_exc  # pragma: no cover

    def _remote_frame_metadata(self, frame: int, silent: bool = False) -> dict | None:
        try:
            head = self.camera.head_image(self.session_id, frame)
        except CameraError:
            if silent:
                return None
            raise
        if head.get("size_bytes") is None:
            return None
        return {
            "sha256": head.get("sha256"),
            "size_bytes": head.get("size_bytes"),
            "width": None,
            "height": None,
            "captured_at": None,
        }

    def _download_and_verify(self, frame: int, meta: dict) -> dict:
        cap = self.config.capture
        part = self.layout.image_part(frame)
        final = self.layout.image_path(frame)
        last_exc: Exception | None = None
        for attempt in range(1, cap.max_download_attempts + 1):
            self.store.update_state(status=Status.DOWNLOADING, current_frame=frame)
            try:
                dl = self.camera.download_image(self.session_id, frame, part)
                self.store.update_state(status=Status.VERIFYING)
                self._verify(frame, part, dl, meta)
                import os

                os.replace(part, final)
                return dl
            except (CameraError, VerificationError) as exc:
                last_exc = exc
                part.unlink(missing_ok=True)
                if attempt == cap.max_download_attempts:
                    self._record_error("download", frame, exc, fatal=True)
                    raise
                self._record_error("download", frame, exc, attempt=attempt)
                self._sleep(cap.retry_delay_seconds * attempt)
        raise last_exc  # pragma: no cover

    def _verify(self, frame: int, part: Path, dl: dict, meta: dict) -> None:
        ctype = (dl.get("content_type") or "").split(";")[0].strip()
        if ctype != "image/jpeg":
            raise VerificationError(f"Frame {frame}: content-type {ctype!r} != image/jpeg")
        if not pkg.is_valid_jpeg(part):
            raise VerificationError(f"Frame {frame}: not a structurally valid JPEG")

        expected_size = meta.get("size_bytes")
        if expected_size is not None and dl["size_bytes"] != expected_size:
            raise VerificationError(
                f"Frame {frame}: size {dl['size_bytes']} != expected {expected_size}"
            )
        if dl.get("declared_size_bytes") is not None and dl["size_bytes"] != dl["declared_size_bytes"]:
            raise VerificationError(
                f"Frame {frame}: truncated download "
                f"({dl['size_bytes']} of {dl['declared_size_bytes']} bytes)"
            )

        if self.config.capture.verify_sha256:
            local = dl["local_sha256"]
            server = dl.get("server_sha256")
            if server and local != server:
                raise VerificationError(
                    f"Frame {frame}: SHA-256 mismatch (local {local[:12]} != "
                    f"server {server[:12]})"
                )
            expected_sha = meta.get("sha256")
            if expected_sha and local != expected_sha.lower():
                raise VerificationError(
                    f"Frame {frame}: SHA-256 mismatch vs capture metadata"
                )

    def _record_frame(self, frame: int, angle: float, meta: dict) -> None:
        final = self.layout.image_path(frame)
        record = FrameRecord(
            frame=frame,
            angle_degrees=angle,
            filename=f"frame_{frame:06d}.jpg",
            sha256=(meta.get("sha256") or pkg.sha256_file(final)),
            size_bytes=meta.get("size_bytes") or final.stat().st_size,
            width=meta.get("width"),
            height=meta.get("height"),
            captured_at=meta.get("captured_at"),
        )
        # Replace any existing record for this frame (resume/retry).
        self.frames = [f for f in self.frames if f.frame != frame]
        self.frames.append(record)
        self.frames.sort(key=lambda f: f.frame)
        self.store.write_frames(self.frames)
        self.store.write_checksums(self.frames)
        self.store.update_state(
            last_completed_frame=frame,
            frames_completed=len(self.frames),
            local_images_verified=len(self.frames),
            remote_images_confirmed=len(self.frames),
        )

    def _record_error(self, phase, frame, exc, attempt=None, fatal=False) -> None:
        self.store.append_error(
            {
                "phase": phase,
                "frame": frame,
                "attempt": attempt,
                "fatal": fatal,
                "error": str(exc),
                "code": getattr(exc, "code", None),
            }
        )
        self.store.update_state(last_error=str(exc))

    # ==================================================================== #
    # Run (spec §14)
    # ==================================================================== #
    def run(self) -> int:
        import signal

        self.print_header()
        self.write_session_manifest()
        self.snapshot_config()
        # Treat SIGTERM like Ctrl-C so the interrupt policy (spec §19) applies.
        previous = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        try:
            self.preflight()
            print(f"[{0:03d}/{self.plan.frame_count - 1:03d}] 0.0°")
            self._sleep(self.config.capture.initial_settle_seconds)
            self.capture_and_pull(0, 0.0)
            print()

            for frame in range(1, self.plan.frame_count):
                target = self.plan.angle_for(frame)
                from_angle = self.plan.angle_for(frame - 1)
                print(f"[{frame:03d}/{self.plan.frame_count - 1:03d}] {target:.1f}°")
                self._move(frame, from_angle, target)
                self.capture_and_pull(frame, target)
                print()

            return self.finalize()
        except KeyboardInterrupt:
            return self._handle_interrupt()
        except ScanError as exc:
            # Movement never advances past a failed capture/download (spec §11,
            # acceptance #11); the table is left in its last assumed state.
            self.store.update_state(
                status=Status.FAILED,
                last_error=str(exc),
                turntable_assumed_state=self.turntable.assumed_state,
            )
            raise
        finally:
            signal.signal(signal.SIGTERM, previous)

    def _handle_interrupt(self) -> int:
        state = self.turntable.assumed_state
        if state == AssumedState.STOPPED:
            self.store.update_state(status=Status.PAUSED)
            print("\nInterrupted. Turntable is stopped; session paused and resumable.")
            from .errors import EXIT_INTERRUPTED

            return EXIT_INTERRUPTED
        self.turntable.mark_unknown()
        self.store.update_state(
            status=Status.PAUSED, turntable_assumed_state=AssumedState.UNKNOWN
        )
        print(
            "\nInterrupted while the turntable may be moving.\n"
            "Turntable state is UNKNOWN. Manually stop it and realign to the last\n"
            "confirmed frame angle before resuming. No emergency stop was sent."
        )
        from .errors import EXIT_TURNTABLE_UNKNOWN

        return EXIT_TURNTABLE_UNKNOWN

    # ==================================================================== #
    # Finalize + validation + package (spec §23, §24)
    # ==================================================================== #
    def finalize(self) -> int:
        self.store.update_state(status=Status.FINALIZING)
        camera_reachable = False
        remote_count = None
        # /status is cheap; record it if we can.
        try:
            end_status = self.camera.status()
            atomic_write_json(
                self.layout.metadata / "camera_status_end.json", end_status
            )
            camera_reachable = True
        except CameraError as exc:
            self._record_error("finalize", None, exc)
        # Remote frame reconciliation is best-effort: every frame was already
        # SHA-256-verified against the server at download time, so a wedged or
        # slow ScannerCam must not sink an otherwise-complete scan. Retry a
        # couple of times, then proceed on the strength of local verification.
        for attempt in range(1, 3):
            try:
                remote_count = len(self.camera.list_images(self.session_id))
                manifest = self.camera.get_manifest(self.session_id)
                atomic_write_json(
                    self.layout.metadata / "scannercam_manifest.json", manifest
                )
                camera_reachable = True
                break
            except CameraError as exc:
                self._record_error("finalize", None, exc, attempt=attempt)
                if attempt < 2:
                    self._sleep(self.config.capture.retry_delay_seconds)

        report = pkg.build_validation_report(
            self.plan,
            self.layout,
            self.frames,
            remote_count,
            self.turntable.assumed_state,
            camera_reachable,
        )
        if report["status"] != "passed":
            self.store.update_state(status=Status.FAILED, last_error="validation failed")
            print(f"\nValidation FAILED: {report}")
            raise VerificationError(
                f"Final validation failed: missing={report['missing_frames']} "
                f"invalid={report['invalid_jpegs']} mismatch={report['hash_mismatches']}"
            )

        completed = self.package(self.layout)
        self._maybe_delete_remote(report)
        self._print_summary(completed)
        return 0

    def package(self, layout: SessionLayout) -> SessionLayout:
        self.store.update_state(status=Status.PACKAGING)
        completed = pkg.build_completed_directory(
            layout,
            self.config.session.completed_root,
            self.session_id,
            self.plan,
            self.frames,
            self._camera_locked,
        )
        # StateStore now points at the moved directory.
        self.layout = completed
        self.store.layout = completed
        archive, sha = pkg.create_archive(
            completed,
            self.config.session.packages_root,
            self.session_id,
            self.config.session.package_format,
        )
        self._archive_path = archive
        self._archive_sha = sha
        self.store.update_state(status=Status.COMPLETE)
        return completed

    def _maybe_delete_remote(self, report: dict) -> None:
        if not self.config.session.delete_remote_after_package:
            return
        if report["status"] != "passed":
            return
        try:
            self.camera.delete_project(self.session_id)
            print(f"Remote project {self.session_id} deleted.")
        except CameraError as exc:
            self._record_error("cleanup", None, exc)
            print(f"Warning: could not delete remote project: {exc}")

    def _print_summary(self, completed: SessionLayout) -> None:
        print("Scan complete.\n")
        print(f"Images verified: {len(self.frames)}/{self.plan.frame_count}")
        print(f"Turntable state: {self.turntable.assumed_state}")
        print(f"Session folder:  {completed.root}")
        if getattr(self, "_archive_path", None):
            print(f"Package:         {self._archive_path}")
            print(f"Checksum:        {self._archive_sha}")

    # ==================================================================== #
    # Resume (spec §21)
    # ==================================================================== #
    def load_existing(self) -> None:
        """Rehydrate frames + state from an interrupted session directory."""
        self.store.load_state()
        frames_file = self.layout.frames_json
        if frames_file.exists():
            import json

            data = json.loads(frames_file.read_text())
            self.frames = [
                FrameRecord(
                    frame=f["frame"],
                    angle_degrees=f["angle_degrees"],
                    filename=f["filename"],
                    sha256=f["sha256"],
                    size_bytes=f["size_bytes"],
                    width=f.get("width"),
                    height=f.get("height"),
                    captured_at=f.get("captured_at"),
                )
                for f in data.get("frames", [])
            ]

    def first_incomplete_frame(self) -> int:
        """Lowest frame index whose local JPEG is missing or invalid."""
        have = set()
        for record in self.frames:
            path = self.layout.image_path(record.frame)
            if path.exists() and pkg.is_valid_jpeg(path):
                have.add(record.frame)
        for frame in range(self.plan.frame_count):
            if frame not in have:
                return frame
        return self.plan.frame_count

    def resume(self) -> int:
        self.load_existing()
        # Reconcile with the remote so we don't re-capture confirmed frames.
        try:
            self.camera.list_images(self.session_id)
        except CameraError as exc:
            raise PreflightError(f"Cannot reach ScannerCam to reconcile: {exc}") from exc

        start = self.first_incomplete_frame()
        if start >= self.plan.frame_count:
            print("All frames already present. Finalizing.")
            return self.finalize()

        last_frame = start - 1
        last_angle = self.plan.angle_for(last_frame) if last_frame >= 0 else 0.0
        next_angle = self.plan.angle_for(start)

        print(f"Last verified frame:\n  {last_frame} at {last_angle:.0f}°\n")
        print(f"Next frame:\n  {start} at {next_angle:.0f}°\n")
        print(
            f"Manually stop the turntable and align the object to {last_angle:.0f}°.\n"
            "The physical angle never survives an interrupted session."
        )
        if not self.assume_yes:
            self._prompt("Press Enter when the table is stopped and aligned... ")

        # After manual realignment we can once again assume 'stopped'.
        self.turntable.assumed_state = AssumedState.STOPPED
        self.preflight()

        for frame in range(start, self.plan.frame_count):
            target = self.plan.angle_for(frame)
            print(f"[{frame:03d}/{self.plan.frame_count - 1:03d}] {target:.1f}°")
            if frame > 0:
                self._move(frame, self.plan.angle_for(frame - 1), target)
            self.capture_and_pull(frame, target)
            print()

        return self.finalize()


def _as_str(value) -> str | None:
    return str(value) if value is not None else None


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt

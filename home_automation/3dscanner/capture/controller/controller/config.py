"""Configuration loading and the movement timing model.

Reads ``config/scanner.yaml`` (spec §8) and, when present, a turntable
calibration profile (spec §17). Paths in the config are resolved relative to
the project root so the controller can be launched from anywhere.

The bearer token is never read from YAML — only from the environment variable
named by ``camera.token_env`` (spec §8, §11).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

# capture/controller/controller/config.py -> 3dscanner
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "scanner.yaml"
DEFAULT_CALIBRATION_PATH = PROJECT_ROOT / "calibration" / "turntable" / "default.yaml"


def _resolve(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    p = Path(path_value)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


@dataclass
class MovementConfig:
    degrees_per_second: float = 12.0
    toggle_command_latency_seconds: float = 0.035
    stop_coast_seconds: float = 0.080
    minimum_run_seconds: float = 0.100


@dataclass
class CameraConfig:
    base_url: str = "http://saru:8765/api/v1"
    fallback_url: str | None = None
    token_env: str = "SCANNERCAM_TOKEN"
    connect_timeout_seconds: float = 5.0
    capture_timeout_seconds: float = 30.0
    download_timeout_seconds: float = 60.0
    require_locks: bool = True


@dataclass
class TurntableConfig:
    driver: str = "arduino_ir"
    serial_port: str | None = None
    baud_rate: int = 115200
    interface_directory: Path | None = None
    gateway_source: Path | None = None
    codes_file: Path | None = None
    controller_module: Path | None = None
    movement: MovementConfig = field(default_factory=MovementConfig)


@dataclass
class CaptureConfig:
    degrees_per_frame: float = 10.0
    initial_settle_seconds: float = 2.0
    settle_seconds: float = 2.0
    max_capture_attempts: int = 3
    max_download_attempts: int = 3
    retry_delay_seconds: float = 2.0
    verify_sha256: bool = True
    download_immediately: bool = True


@dataclass
class SessionConfig:
    scans_root: Path = PROJECT_ROOT / "scans" / "incoming"
    completed_root: Path = PROJECT_ROOT / "scans" / "completed"
    failed_root: Path = PROJECT_ROOT / "scans" / "failed"
    packages_root: Path = PROJECT_ROOT / "output" / "packages"
    package_format: str = "tar.gz"
    delete_remote_after_package: bool = False


@dataclass
class Calibration:
    """Optional per-step run-second overrides (spec §17)."""

    profile_id: str = "default"
    nominal_degrees_per_second: float | None = None
    toggle_command_latency_seconds: float | None = None
    stop_coast_seconds: float | None = None
    step_overrides: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Calibration | None":
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text()) or {}
        timing = data.get("timing", {}) or {}
        overrides = {}
        for step, body in (data.get("step_overrides", {}) or {}).items():
            if isinstance(body, dict) and "run_seconds" in body:
                overrides[str(step)] = float(body["run_seconds"])
        return cls(
            profile_id=str(data.get("profile_id", "default")),
            nominal_degrees_per_second=data.get("nominal_degrees_per_second"),
            toggle_command_latency_seconds=timing.get("toggle_command_latency_seconds"),
            stop_coast_seconds=timing.get("stop_coast_seconds"),
            step_overrides=overrides,
        )


@dataclass
class Config:
    scanner_name: str
    camera: CameraConfig
    turntable: TurntableConfig
    capture: CaptureConfig
    session: SessionConfig
    calibration: Calibration | None
    source_path: Path
    raw: dict[str, Any]

    # -- Loading ------------------------------------------------------------ #
    @classmethod
    def load(
        cls,
        config_path: Path | None = None,
        calibration_path: Path | None = None,
    ) -> "Config":
        path = config_path or DEFAULT_CONFIG_PATH
        if not path.exists():
            raise ConfigError(
                f"Config not found: {path}\n"
                "Copy config/scanner.example.yaml to config/scanner.yaml and edit it."
            )
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Could not parse {path}: {exc}") from exc

        cam = data.get("camera", {}) or {}
        tt = data.get("turntable", {}) or {}
        mv = tt.get("movement", {}) or {}
        cap = data.get("capture", {}) or {}
        sess = data.get("session", {}) or {}
        scanner = data.get("scanner", {}) or {}

        camera = CameraConfig(
            base_url=cam.get("base_url", CameraConfig.base_url),
            fallback_url=cam.get("fallback_url"),
            token_env=cam.get("token_env", CameraConfig.token_env),
            connect_timeout_seconds=float(cam.get("connect_timeout_seconds", 5.0)),
            capture_timeout_seconds=float(cam.get("capture_timeout_seconds", 30.0)),
            download_timeout_seconds=float(cam.get("download_timeout_seconds", 60.0)),
            require_locks=bool(cam.get("require_locks", True)),
        )

        turntable = TurntableConfig(
            driver=tt.get("driver", "arduino_ir"),
            serial_port=tt.get("serial_port"),
            baud_rate=int(tt.get("baud_rate", 115200)),
            interface_directory=_resolve(tt.get("interface_directory")),
            gateway_source=_resolve(tt.get("gateway_source")),
            codes_file=_resolve(tt.get("codes_file")),
            controller_module=_resolve(tt.get("controller_module")),
            movement=MovementConfig(
                degrees_per_second=float(mv.get("degrees_per_second", 12.0)),
                toggle_command_latency_seconds=float(
                    mv.get("toggle_command_latency_seconds", 0.035)
                ),
                stop_coast_seconds=float(mv.get("stop_coast_seconds", 0.080)),
                minimum_run_seconds=float(mv.get("minimum_run_seconds", 0.100)),
            ),
        )

        capture = CaptureConfig(
            degrees_per_frame=float(cap.get("degrees_per_frame", 10.0)),
            initial_settle_seconds=float(cap.get("initial_settle_seconds", 2.0)),
            settle_seconds=float(cap.get("settle_seconds", 2.0)),
            max_capture_attempts=int(cap.get("max_capture_attempts", 3)),
            max_download_attempts=int(cap.get("max_download_attempts", 3)),
            retry_delay_seconds=float(cap.get("retry_delay_seconds", 2.0)),
            verify_sha256=bool(cap.get("verify_sha256", True)),
            download_immediately=bool(cap.get("download_immediately", True)),
        )

        session = SessionConfig(
            scans_root=_resolve(sess.get("scans_root")) or SessionConfig.scans_root,
            completed_root=_resolve(sess.get("completed_root"))
            or SessionConfig.completed_root,
            failed_root=_resolve(sess.get("failed_root")) or SessionConfig.failed_root,
            packages_root=_resolve(sess.get("packages_root"))
            or SessionConfig.packages_root,
            package_format=sess.get("package_format", "tar.gz"),
            delete_remote_after_package=bool(
                sess.get("delete_remote_after_package", False)
            ),
        )

        calibration = Calibration.load(calibration_path or DEFAULT_CALIBRATION_PATH)

        return cls(
            scanner_name=scanner.get("name", "scanner"),
            camera=camera,
            turntable=turntable,
            capture=capture,
            session=session,
            calibration=calibration,
            source_path=path,
            raw=data,
        )

    # -- Token -------------------------------------------------------------- #
    def token(self, required: bool = True) -> str | None:
        value = os.environ.get(self.camera.token_env)
        if not value and required:
            raise ConfigError(
                f"Bearer token not set. Export ${self.camera.token_env} with the "
                "token from ScannerCam's Settings screen on saru.",
            )
        return value

    # -- Movement timing (spec §17) ---------------------------------------- #
    def run_seconds_for(self, degrees: float) -> float:
        """Seconds to hold the table running to sweep ``degrees``.

        A calibration step override wins outright. Otherwise the formula:
        ideal minus command latency and stop coast, floored at the minimum.
        """
        mv = self.turntable.movement

        if self.calibration:
            key = _step_key(degrees)
            if key in self.calibration.step_overrides:
                return self.calibration.step_overrides[key]

        dps = mv.degrees_per_second
        if self.calibration and self.calibration.nominal_degrees_per_second:
            dps = self.calibration.nominal_degrees_per_second
        if dps <= 0:
            raise ConfigError("degrees_per_second must be > 0 to compute run time.")

        latency = mv.toggle_command_latency_seconds
        coast = mv.stop_coast_seconds
        if self.calibration:
            if self.calibration.toggle_command_latency_seconds is not None:
                latency = self.calibration.toggle_command_latency_seconds
            if self.calibration.stop_coast_seconds is not None:
                coast = self.calibration.stop_coast_seconds

        ideal = degrees / dps
        run = ideal - latency - coast
        return max(run, mv.minimum_run_seconds)

    def degrees_per_second(self) -> float:
        if self.calibration and self.calibration.nominal_degrees_per_second:
            return self.calibration.nominal_degrees_per_second
        return self.turntable.movement.degrees_per_second


def _step_key(degrees: float) -> str:
    """Match calibration keys like "5" or "10" (ints render without ".0")."""
    if float(degrees).is_integer():
        return str(int(degrees))
    return str(degrees)

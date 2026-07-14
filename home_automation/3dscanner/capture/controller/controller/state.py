"""Session directory layout, atomic persistence, and the controller lock.

Every meaningful state transition is flushed to ``state.json`` atomically
(temp file + ``os.replace``) so an interrupted session can always be resumed
from a consistent snapshot (spec §12, §21).
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError, ScanError
from .models import SCHEMA_VERSION, FrameRecord, now_iso


# --- atomic helpers -------------------------------------------------------- #
def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2) + "\n")


# --- session layout -------------------------------------------------------- #
@dataclass
class SessionLayout:
    root: Path

    @property
    def images(self) -> Path:
        return self.root / "images"

    @property
    def metadata(self) -> Path:
        return self.root / "metadata"

    @property
    def diagnostics(self) -> Path:
        return self.root / "diagnostics"

    @property
    def session_json(self) -> Path:
        return self.root / "session.json"

    @property
    def state_json(self) -> Path:
        return self.root / "state.json"

    @property
    def config_snapshot(self) -> Path:
        return self.root / "config.snapshot.yaml"

    @property
    def scan_log(self) -> Path:
        return self.root / "scan.log"

    @property
    def frames_json(self) -> Path:
        return self.metadata / "frames.json"

    @property
    def checksums(self) -> Path:
        return self.metadata / "checksums.sha256"

    @property
    def timing_csv(self) -> Path:
        return self.diagnostics / "timing.csv"

    @property
    def errors_jsonl(self) -> Path:
        return self.diagnostics / "errors.jsonl"

    def image_path(self, frame: int) -> Path:
        return self.images / f"frame_{frame:06d}.jpg"

    def image_part(self, frame: int) -> Path:
        return self.images / f".frame_{frame:06d}.jpg.part"

    def create_skeleton(self) -> None:
        self.images.mkdir(parents=True, exist_ok=True)
        self.metadata.mkdir(parents=True, exist_ok=True)
        self.diagnostics.mkdir(parents=True, exist_ok=True)


_TIMING_HEADER = (
    "frame,from_angle_degrees,to_angle_degrees,requested_step_degrees,"
    "calculated_run_seconds,start_toggle_sent_at,stop_toggle_sent_at,"
    "settle_completed_at\n"
)


class StateStore:
    """Owns state.json and the per-session diagnostic files."""

    def __init__(self, layout: SessionLayout):
        self.layout = layout
        self.state: dict = {}

    # -- session.json ------------------------------------------------------- #
    def write_session_manifest(self, manifest: dict) -> None:
        atomic_write_json(self.layout.session_json, manifest)

    def load_session_manifest(self) -> dict:
        return json.loads(self.layout.session_json.read_text())

    # -- state.json --------------------------------------------------------- #
    def init_state(self, **fields) -> None:
        self.state = {"schema_version": SCHEMA_VERSION, **fields}
        self._flush_state()

    def load_state(self) -> dict:
        self.state = json.loads(self.layout.state_json.read_text())
        return self.state

    def update_state(self, **fields) -> None:
        self.state.update(fields)
        self._flush_state()

    def _flush_state(self) -> None:
        self.state["updated_at"] = now_iso()
        atomic_write_json(self.layout.state_json, self.state)

    # -- frames.json / checksums ------------------------------------------- #
    def write_frames(self, frames: list[FrameRecord]) -> None:
        atomic_write_json(
            self.layout.frames_json,
            {
                "schema_version": SCHEMA_VERSION,
                "frames": [f.to_dict() for f in frames],
            },
        )

    def write_checksums(self, frames: list[FrameRecord]) -> None:
        lines = [f"{f.sha256}  images/{f.filename}\n" for f in frames]
        atomic_write_text(self.layout.checksums, "".join(lines))

    # -- diagnostics -------------------------------------------------------- #
    def append_timing(
        self,
        frame: int,
        from_angle: float,
        to_angle: float,
        requested_step: float,
        run_seconds: float,
        start_ts: str | None,
        stop_ts: str | None,
        settle_ts: str | None,
    ) -> None:
        path = self.layout.timing_csv
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(_TIMING_HEADER)
        row = (
            f"{frame},{from_angle},{to_angle},{requested_step},{run_seconds},"
            f"{start_ts or ''},{stop_ts or ''},{settle_ts or ''}\n"
        )
        with open(path, "a") as handle:
            handle.write(row)

    def append_error(self, entry: dict) -> None:
        path = self.layout.errors_jsonl
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": now_iso(), **entry}
        with open(path, "a") as handle:
            handle.write(json.dumps(entry) + "\n")


# --- controller lock (spec §22) -------------------------------------------- #
class ControllerLock:
    """Single-process turntable lock at ``scans/.controller.lock``."""

    def __init__(self, lock_path: Path, session_id: str):
        self.lock_path = lock_path
        self.session_id = session_id
        self._held = False

    def acquire(self) -> None:
        if self.lock_path.exists():
            try:
                existing = json.loads(self.lock_path.read_text())
            except (json.JSONDecodeError, OSError):
                existing = {}
            pid = existing.get("pid")
            if pid and _pid_alive(pid):
                raise ConfigError(
                    f"Another scan controller is running (pid {pid}, session "
                    f"{existing.get('session_id')}). Lock: {self.lock_path}"
                )
            # Stale lock from a dead process — reclaim it.
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.lock_path,
            {
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "session_id": self.session_id,
                "created_at": now_iso(),
            },
        )
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        try:
            current = json.loads(self.lock_path.read_text())
            if current.get("pid") == os.getpid():
                self.lock_path.unlink()
        except (OSError, json.JSONDecodeError):
            pass
        self._held = False

    def __enter__(self) -> "ControllerLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    except OSError:
        return False
    return True

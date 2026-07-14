"""Shared value objects and constants for the scan controller.

These are plain data holders with no I/O. ``session.py`` owns the behaviour;
this module owns the shapes that get serialised into ``session.json`` and
``state.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


SCHEMA_VERSION = 1


# --- Runtime status values (spec §12) -------------------------------------- #
class Status:
    INITIALIZING = "initializing"
    PREFLIGHT = "preflight"
    READY = "ready"
    MOVING = "moving"
    SETTLING = "settling"
    CAPTURING = "capturing"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    FINALIZING = "finalizing"
    PACKAGING = "packaging"
    COMPLETE = "complete"
    PAUSED = "paused"
    FAILED = "failed"


# --- Assumed turntable state (spec §4) ------------------------------------- #
class AssumedState:
    STOPPED = "stopped"
    RUNNING = "running"
    UNKNOWN = "unknown"


def now_iso() -> str:
    """Timezone-aware ISO 8601 timestamp with offset, e.g. ...+09:00."""
    return datetime.now().astimezone().isoformat()


def make_session_id(display_name: str, when: datetime | None = None) -> str:
    """``red_mug`` -> ``20260714-151422-red_mug`` (spec §9)."""
    when = when or datetime.now()
    return f"{when.strftime('%Y%m%d-%H%M%S')}-{display_name}"


@dataclass
class CapturePlan:
    """Derived geometry of a scan (spec §3, §11)."""

    degrees_per_frame: float
    frame_count: int
    first_angle_degrees: float
    last_angle_degrees: float
    settle_seconds: float

    @classmethod
    def from_step(cls, degrees_per_frame: float, settle_seconds: float) -> "CapturePlan":
        frame_count = round(360.0 / degrees_per_frame)
        return cls(
            degrees_per_frame=float(degrees_per_frame),
            frame_count=frame_count,
            first_angle_degrees=0.0,
            last_angle_degrees=(frame_count - 1) * float(degrees_per_frame),
            settle_seconds=float(settle_seconds),
        )

    def angle_for(self, frame: int) -> float:
        return frame * self.degrees_per_frame

    def to_dict(self) -> dict:
        return {
            "degrees_per_frame": self.degrees_per_frame,
            "frame_count": self.frame_count,
            "first_angle_degrees": self.first_angle_degrees,
            "last_angle_degrees": self.last_angle_degrees,
            "settle_seconds": self.settle_seconds,
        }


@dataclass
class FrameRecord:
    """One captured, downloaded, and verified frame (persisted to frames.json)."""

    frame: int
    angle_degrees: float
    filename: str
    sha256: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    captured_at: str | None = None
    downloaded_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {
            "frame": self.frame,
            "angle_degrees": self.angle_degrees,
            "filename": self.filename,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
            "captured_at": self.captured_at,
            "downloaded_at": self.downloaded_at,
        }

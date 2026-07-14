"""Turntable controller interface and the movement result record.

The physical turntable is driven by a single IR toggle (spec §4): one press
starts the (pre-armed, continuous, clockwise) rotation, the next press stops
it. Because the signal is a *toggle*, the controller can never read or force
the real state — it can only track an assumed state and refuse to act when
that assumption is broken.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from controller.errors import TurntableStateUnknown
from controller.models import AssumedState


@dataclass
class MoveResult:
    """One rotation step, for diagnostics/timing.csv (spec §18)."""

    from_angle_degrees: float
    to_angle_degrees: float
    requested_step_degrees: float
    calculated_run_seconds: float
    start_toggle_sent_at: str | None = None
    stop_toggle_sent_at: str | None = None
    settle_completed_at: str | None = None


class TurntableController(ABC):
    driver = "base"
    control_type = "single_toggle_start_stop"

    def __init__(self) -> None:
        # Sessions start with the table confirmed stopped (spec §4).
        self.assumed_state = AssumedState.STOPPED

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def toggle(self) -> None:
        """Send exactly one start/stop toggle (START_PAUSE)."""

    @abstractmethod
    def move_by_degrees(self, degrees: float, run_seconds: float | None = None) -> MoveResult:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    # -- assumed-state helpers (spec §4, §19) ------------------------------ #
    def require_stopped(self) -> None:
        """Refuse to move unless we are certain the table is stopped."""
        if self.assumed_state != AssumedState.STOPPED:
            raise TurntableStateUnknown(
                f"Turntable assumed state is '{self.assumed_state}', not 'stopped'. "
                "Manually stop the turntable and realign before continuing."
            )

    def mark_unknown(self) -> None:
        self.assumed_state = AssumedState.UNKNOWN

    def describe(self) -> str:
        return f"{self.driver} ({self.control_type})"

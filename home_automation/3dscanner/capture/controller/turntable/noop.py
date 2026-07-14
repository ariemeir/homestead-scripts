"""No-op / manual turntable driver (spec §27 ``--turntable noop``).

No Arduino involved. In manual mode the operator rotates the table by hand and
confirms; in unattended mode the step is simply skipped. Either way the table
is only ever moved while the operator is present, so the assumed state stays
``stopped`` throughout — there is no toggle that could leave it uncertain.
"""

from __future__ import annotations

import time
from typing import Callable

from controller.models import now_iso
from .base import MoveResult, TurntableController


class NoOpTurntableController(TurntableController):
    driver = "noop"
    control_type = "manual"

    def __init__(
        self,
        interactive: bool = True,
        *,
        prompt: Callable[[str], str] = input,
        clock: Callable[[], str] = now_iso,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__()
        self.interactive = interactive
        self._prompt = prompt
        self._clock = clock
        self._sleep = sleep

    def connect(self) -> None:
        return None

    def toggle(self) -> None:
        return None

    def move_by_degrees(self, degrees: float, run_seconds: float | None = None) -> MoveResult:
        start = self._clock()
        if self.interactive:
            self._prompt(
                f"  Manually rotate the turntable by {degrees:g}°, "
                "then press Enter..."
            )
        else:
            print(f"  [noop] rotate by {degrees:g}° (skipped, unattended)")
        stop = self._clock()
        return MoveResult(
            from_angle_degrees=0.0,
            to_angle_degrees=0.0,
            requested_step_degrees=float(degrees),
            calculated_run_seconds=0.0,
            start_toggle_sent_at=start,
            stop_toggle_sent_at=stop,
        )

    def close(self) -> None:
        return None

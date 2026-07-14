"""Arduino IR turntable driver.

Wraps the existing firmware interface at ``firmware/turntable_ir/turntable.py``
(the source of truth for IR codes and the serial protocol). No IR codes or
Arduino command details are duplicated here — this module only adds the
start/stop *timing* and the assumed-state safety machine (spec §6, §17, §19).

The physical remote is pre-armed by the operator to continuous, clockwise
rotation at a known speed; ``START_PAUSE`` then toggles motion on and off.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Callable

from controller.errors import TurntableError, TurntableStateUnknown
from controller.models import AssumedState, now_iso
from .base import MoveResult, TurntableController

# The IR button that starts/pauses the pre-armed rotation program (confirmed
# against firmware/turntable_ir/turntable_codes.json — there is no literal
# "toggle" button; START_PAUSE is the run/pause toggle).
TOGGLE_BUTTON = "START_PAUSE"


def _load_firmware_module(module_path: Path):
    """Import firmware/turntable_ir/turntable.py by path (it is not a package)."""
    if not module_path or not Path(module_path).exists():
        raise TurntableError(
            f"Turntable firmware interface not found: {module_path}. "
            "Set turntable.controller_module in config/scanner.yaml."
        )
    spec = importlib.util.spec_from_file_location("turntable_firmware", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArduinoIRTurntableController(TurntableController):
    driver = "arduino_ir"
    control_type = "single_toggle_start_stop"

    def __init__(
        self,
        controller_module: Path,
        serial_port: str | None,
        baud_rate: int = 115200,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], str] = now_iso,
        turntable=None,
    ):
        super().__init__()
        self.controller_module = controller_module
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self._sleep = sleep
        self._clock = clock
        self._turntable = turntable  # injected in tests; built by connect() otherwise
        self._gateway = None

    # -- lifecycle ---------------------------------------------------------- #
    def connect(self) -> None:
        if self._turntable is not None:
            return  # pre-injected (tests)
        if not self.serial_port:
            raise TurntableError(
                "No serial_port configured for the Arduino turntable driver."
            )
        firmware = _load_firmware_module(self.controller_module)
        try:
            self._gateway = firmware.SerialGateway(self.serial_port, self.baud_rate)
        except ImportError as exc:
            raise TurntableError(
                "pyserial is required for the Arduino driver: pip install pyserial"
            ) from exc
        except Exception as exc:  # serial.SerialException and friends
            raise TurntableError(
                f"Could not open serial port {self.serial_port}: {exc}"
            ) from exc
        if not self._gateway.ping():
            raise TurntableError(
                f"No PONG from the IR gateway on {self.serial_port}. "
                "Is ir_send_gateway.ino flashed and the right port selected?"
            )
        config = firmware.load_config()
        self._turntable = firmware.Turntable(self._gateway, config)
        # Fail fast if the firmware code table lacks the toggle button.
        if TOGGLE_BUTTON not in self._turntable.buttons:
            raise TurntableError(
                f"IR code table has no {TOGGLE_BUTTON!r} button."
            )

    def toggle(self) -> None:
        if self._turntable is None:
            raise TurntableError("Turntable not connected.")
        self._turntable.press(TOGGLE_BUTTON)

    # -- movement (spec §6) ------------------------------------------------- #
    def move_by_degrees(self, degrees: float, run_seconds: float | None = None) -> MoveResult:
        self.require_stopped()
        if run_seconds is None:
            raise TurntableError("run_seconds must be supplied by the caller.")

        result = MoveResult(
            from_angle_degrees=0.0,
            to_angle_degrees=0.0,
            requested_step_degrees=float(degrees),
            calculated_run_seconds=float(run_seconds),
        )

        # Start toggle. Any failure here is ambiguous (the IR may or may not
        # have gone out), so we drop to 'unknown' rather than assume stopped.
        try:
            self.toggle()
        except Exception as exc:
            self.mark_unknown()
            raise TurntableStateUnknown(
                f"Start toggle failed; turntable state is now unknown: {exc}"
            ) from exc
        self.assumed_state = AssumedState.RUNNING
        result.start_toggle_sent_at = self._clock()

        self._sleep(run_seconds)

        # Stop toggle. If this fails the table is very likely still running.
        try:
            self.toggle()
        except Exception as exc:
            self.mark_unknown()
            raise TurntableStateUnknown(
                f"Stop toggle failed; turntable may still be running: {exc}"
            ) from exc
        self.assumed_state = AssumedState.STOPPED
        result.stop_toggle_sent_at = self._clock()
        return result

    def close(self) -> None:
        if self._gateway is not None:
            try:
                self._gateway.close()
            finally:
                self._gateway = None

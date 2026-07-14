"""Turntable drivers and a factory keyed on the configured driver name."""

from __future__ import annotations

from controller.config import Config
from controller.errors import ConfigError
from .base import MoveResult, TurntableController
from .noop import NoOpTurntableController
from .arduino_ir import ArduinoIRTurntableController

__all__ = [
    "MoveResult",
    "TurntableController",
    "NoOpTurntableController",
    "ArduinoIRTurntableController",
    "build_turntable",
]


def build_turntable(
    config: Config,
    driver: str | None = None,
    *,
    interactive: bool = True,
) -> TurntableController:
    """Instantiate the driver named by ``driver`` (or config), unconnected."""
    name = driver or config.turntable.driver
    if name == "noop":
        return NoOpTurntableController(interactive=interactive)
    if name == "arduino_ir":
        return ArduinoIRTurntableController(
            controller_module=config.turntable.controller_module,
            serial_port=config.turntable.serial_port,
            baud_rate=config.turntable.baud_rate,
        )
    raise ConfigError(f"Unknown turntable driver: {name!r} (use arduino_ir or noop).")

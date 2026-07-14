"""Turntable driver + assumed-state safety machine (spec §4, §6, §19)."""

import pytest

from controller.errors import TurntableStateUnknown
from controller.models import AssumedState
from turntable.arduino_ir import ArduinoIRTurntableController, TOGGLE_BUTTON
from turntable.noop import NoOpTurntableController


class FakeTurntable:
    """Stands in for firmware.Turntable — records presses, can be made to fail."""

    def __init__(self, fail_on=None):
        self.presses = []
        self.buttons = {TOGGLE_BUTTON: {"raw": 1}}
        self.fail_on = fail_on  # 1-based press index to raise on

    def press(self, key):
        self.presses.append(key)
        if self.fail_on is not None and len(self.presses) == self.fail_on:
            raise RuntimeError("gateway error")


def make_arduino(fake):
    return ArduinoIRTurntableController(
        controller_module=None,
        serial_port=None,
        sleep=lambda s: None,
        clock=lambda: "T",
        turntable=fake,
    )


def test_move_toggles_twice_and_returns_to_stopped():
    fake = FakeTurntable()
    tt = make_arduino(fake)
    result = tt.move_by_degrees(10.0, run_seconds=0.4)
    assert fake.presses == [TOGGLE_BUTTON, TOGGLE_BUTTON]
    assert tt.assumed_state == AssumedState.STOPPED
    assert result.calculated_run_seconds == 0.4
    assert result.start_toggle_sent_at == "T"
    assert result.stop_toggle_sent_at == "T"


def test_move_requires_stopped_state():
    tt = make_arduino(FakeTurntable())
    tt.assumed_state = AssumedState.UNKNOWN
    with pytest.raises(TurntableStateUnknown):
        tt.move_by_degrees(10.0, run_seconds=0.4)


def test_start_toggle_failure_marks_unknown():
    fake = FakeTurntable(fail_on=1)  # first (start) toggle fails
    tt = make_arduino(fake)
    with pytest.raises(TurntableStateUnknown):
        tt.move_by_degrees(10.0, run_seconds=0.4)
    assert tt.assumed_state == AssumedState.UNKNOWN


def test_stop_toggle_failure_marks_unknown():
    fake = FakeTurntable(fail_on=2)  # second (stop) toggle fails
    tt = make_arduino(fake)
    with pytest.raises(TurntableStateUnknown):
        tt.move_by_degrees(10.0, run_seconds=0.4)
    assert tt.assumed_state == AssumedState.UNKNOWN
    assert fake.presses == [TOGGLE_BUTTON, TOGGLE_BUTTON]


def test_move_without_run_seconds_errors():
    from controller.errors import TurntableError

    tt = make_arduino(FakeTurntable())
    with pytest.raises(TurntableError):
        tt.move_by_degrees(10.0)


def test_noop_stays_stopped_and_prompts():
    prompts = []
    tt = NoOpTurntableController(
        interactive=True, prompt=lambda m: prompts.append(m) or "", clock=lambda: "T"
    )
    tt.connect()
    tt.move_by_degrees(10.0)
    assert tt.assumed_state == AssumedState.STOPPED
    assert len(prompts) == 1


def test_noop_unattended_does_not_prompt():
    def boom(_):
        raise AssertionError("should not prompt when unattended")

    tt = NoOpTurntableController(interactive=False, prompt=boom, clock=lambda: "T")
    tt.move_by_degrees(10.0)
    assert tt.assumed_state == AssumedState.STOPPED

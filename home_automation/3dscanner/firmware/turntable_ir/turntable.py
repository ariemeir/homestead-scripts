#!/usr/bin/env python3
"""
Turntable controller.

Pipeline:   this script  --USB serial-->  Arduino (IR LED)  --IR-->  turntable

Files:      turntable_codes.json     captured button codes (source of truth)
            ir_send_gateway.ino      firmware running on the Uno
Dependency: pip install pyserial

Examples:
    python turntable.py demo                          # dry run, no hardware
    python turntable.py run   --port /dev/cu.usbserial-1420
    python turntable.py press CW --port COM5
    python turntable.py repl  --port /dev/ttyUSB0     # type button names live

Find your port:  macOS `ls /dev/cu.*` | Linux `ls /dev/ttyUSB* /dev/ttyACM*` |
                 Windows: Device Manager > Ports (COMx)
"""

from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

CONFIG = Path(__file__).with_name("turntable_codes.json")

ANGLES = {45: "ANGLE_45", 90: "ANGLE_90", 180: "ANGLE_180"}
MODES = {
    "continuous": "ROTATE_CONTINUOUS",
    "intermittent": "ROTATE_INTERMITTENT",
    "step90": "STEP_90",
}


# --------------------------------------------------------------------------- #
# Gateway (transport): the only thing that changes between dry-run and hardware
# --------------------------------------------------------------------------- #
class Gateway:
    def send_raw(self, raw: int, repeats: int = 0) -> None:
        raise NotImplementedError

    def ping(self) -> bool:
        """True if the gateway is reachable. Base/mock transports always are."""
        return True

    def close(self) -> None:
        pass


class MockGateway(Gateway):
    """Prints instead of transmitting. Run the whole thing with no hardware."""

    def send_raw(self, raw: int, repeats: int = 0) -> None:
        print(f"    [IR] raw=0x{raw:08X} rep={repeats}")


class SerialGateway(Gateway):
    """Talks to ir_send_gateway.ino over USB serial."""

    def __init__(self, port: str, baud: int = 115200, timeout: float = 2.0):
        import serial  # pyserial, imported lazily so the mock path needs nothing
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(2.0)                      # Uno reboots when the port opens
        self.ser.reset_input_buffer()
        if not self._ping():
            print("warning: no PONG - is ir_send_gateway.ino flashed and the "
                  "right port selected?", file=sys.stderr)

    def _cmd(self, line: str) -> str:
        self.ser.write((line + "\n").encode())
        return self.ser.readline().decode(errors="replace").strip()

    def _ping(self) -> bool:
        return self._cmd("PING") == "PONG"

    def ping(self) -> bool:
        return self._ping()

    def send_raw(self, raw: int, repeats: int = 0) -> None:
        resp = self._cmd(f"R {raw:08X} {repeats}")
        if not resp.startswith("OK"):
            raise RuntimeError(f"gateway error: {resp!r}")

    def close(self) -> None:
        self.ser.close()


# --------------------------------------------------------------------------- #
# Controller: hardware-agnostic, driven by the captured JSON
# --------------------------------------------------------------------------- #
class Turntable:
    def __init__(self, gateway: Gateway, config: dict, press_gap: float = 0.3):
        self.gw = gateway
        self.buttons = config["buttons"]
        self.press_gap = press_gap

    def press(self, key: str, repeats: int = 0) -> None:
        entry = self.buttons.get(key)
        if not entry or entry.get("skipped"):
            raise KeyError(f"no captured code for {key!r}")
        print(f"  press {key}")
        self.gw.send_raw(int(entry["raw"]), repeats)

    def _repeat(self, key: str, n: int) -> None:
        for i in range(max(1, n)):
            self.press(key)
            if i < n - 1:
                time.sleep(self.press_gap)

    # ---- high-level API (matches the physical remote) -------------------- #
    def power(self):        self.press("POWER")            # on/off toggle
    def start_pause(self):  self.press("START_PAUSE")
    def cw(self):           self.press("CW")               # rotate clockwise
    def ccw(self):          self.press("CCW")              # rotate counter-cw
    def set_home(self):     self.press("SET_HOME")
    def return_home(self):  self.press("RETURN_HOME")

    def mode(self, name: str):
        if name not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}")
        self.press(MODES[name])

    def angle(self, deg: int):
        if deg not in ANGLES:
            raise ValueError(f"angle must be one of {list(ANGLES)}")
        self.press(ANGLES[deg])

    def speed_up(self, n: int = 1):   self._repeat("SPEED_UP", n)
    def speed_down(self, n: int = 1): self._repeat("SPEED_DOWN", n)


# --------------------------------------------------------------------------- #
# Wiring helpers + CLI
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    if not CONFIG.exists():
        sys.exit(f"missing {CONFIG.name} next to this script")
    return json.loads(CONFIG.read_text())


def make_gateway(port):
    return SerialGateway(port) if port else MockGateway()


def demo(t: Turntable) -> None:
    print("Demo sequence:")
    print("\n1) Power on, rotate clockwise")
    t.power()
    t.cw()
    print("\n2) Nudge speed up twice")
    t.speed_up(2)
    print("\n3) Switch to 90-degree sweep")
    t.angle(90)
    print("\n4) Reverse to counter-clockwise, then intermittent mode")
    t.ccw()
    t.mode("intermittent")
    print("\n5) Return home and power off")
    t.return_home()
    t.power()


def repl(t: Turntable) -> None:
    keys = ", ".join(k for k, v in t.buttons.items() if not v.get("skipped"))
    print(f"Type a button name and Enter. Available:\n  {keys}\nCtrl-D to quit.")
    while True:
        try:
            key = input("> ").strip().upper()
        except EOFError:
            print()
            break
        if not key:
            continue
        try:
            t.press(key)
        except KeyError as e:
            print(f"  {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Turntable IR controller")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    p_run = sub.add_parser("run");   p_run.add_argument("--port", required=True)
    p_repl = sub.add_parser("repl"); p_repl.add_argument("--port", required=True)
    p_press = sub.add_parser("press")
    p_press.add_argument("key")
    p_press.add_argument("--port", default=None)
    args = ap.parse_args()

    config = load_config()
    gw = make_gateway(getattr(args, "port", None))
    t = Turntable(gw, config)
    try:
        if args.cmd == "demo":
            demo(t)
        elif args.cmd == "run":
            demo(t)
        elif args.cmd == "repl":
            repl(t)
        elif args.cmd == "press":
            t.press(args.key.upper())
    finally:
        gw.close()


if __name__ == "__main__":
    main()

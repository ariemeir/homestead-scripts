#!/usr/bin/env python3
"""
irctl — command-line control for the DIY IR blaster.

Talks to an Arduino running ir_blaster.ino over USB serial, looks button
names up in a captured JSON config, and fires the matching IR code.

    ./irctl.py list                     # what buttons do I have?
    ./irctl.py send POWER               # fire one
    ./irctl.py send CW SPEED_UP SPEED_UP    # fire a sequence
    ./irctl.py send POWER --repeat 2    # extra NEC repeat frames
    ./irctl.py learn MUTE               # learn a new button, save to config
    ./irctl.py mon                      # watch every frame the receiver sees
    ./irctl.py repl                     # interactive
    ./irctl.py ports                    # list serial ports

The port is auto-detected; override with --port /dev/cu.usbserial-1420.
Config defaults to turntable_codes.json beside this script; --config for others.
Add --dry-run to any command to print instead of transmit.

Requires: pip install pyserial
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).with_name("turntable_codes.json")
BAUD = 115200

# USB serial chips commonly found on Unos and clones.
PORT_HINTS = ("usbmodem", "usbserial", "ttyacm", "ttyusb", "arduino", "ch340",
              "ch910", "wch", "cp210", "ftdi")


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #
def _require_serial():
    try:
        import serial  # noqa: F401
        return serial
    except ImportError:
        sys.exit("pyserial is not installed.  pip install pyserial")


def list_ports():
    _require_serial()
    from serial.tools import list_ports as lp
    return list(lp.comports())


def autodetect_port() -> str:
    ports = list_ports()
    if not ports:
        sys.exit("No serial ports found. Is the Arduino plugged in?")
    for p in ports:
        blob = f"{p.device} {p.description} {p.manufacturer or ''}".lower()
        if any(h in blob for h in PORT_HINTS):
            return p.device
    if len(ports) == 1:
        return ports[0].device
    listing = "\n".join(f"  {p.device}  {p.description}" for p in ports)
    sys.exit(f"Couldn't pick a port automatically. Use --port with one of:\n{listing}")


class Blaster:
    """Thin wrapper over the ir_blaster.ino serial protocol."""

    def __init__(self, port: str | None, dry_run: bool = False, quiet: bool = False):
        self.dry_run = dry_run
        self.quiet = quiet
        if dry_run:
            self.ser = None
            return
        serial = _require_serial()
        self.port = port or autodetect_port()
        try:
            self.ser = serial.Serial(self.port, BAUD, timeout=2.0)
        except Exception as e:
            sys.exit(f"Could not open {self.port}: {e}")
        time.sleep(2.0)              # the Uno reboots when the port opens
        self.ser.reset_input_buffer()
        if not self.ping():
            print(f"warning: no PONG from {self.port} — is ir_blaster.ino flashed?",
                  file=sys.stderr)

    def cmd(self, line: str) -> str:
        if self.dry_run:
            print(f"  [dry-run] {line}")
            return "OK dry-run"
        self.ser.write((line + "\n").encode())
        return self.ser.readline().decode(errors="replace").strip()

    def ping(self) -> bool:
        return self.cmd("PING") == "PONG"

    def send_raw(self, raw: int, repeats: int = 0) -> str:
        return self.cmd(f"R {raw:08X} {repeats}")

    def readline(self) -> str:
        if self.dry_run:
            return ""
        return self.ser.readline().decode(errors="replace").strip()

    def close(self):
        if self.ser:
            self.ser.close()


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"No config at {path}. Capture codes first, or pass --config.")
    try:
        cfg = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"{path} is not valid JSON: {e}")
    cfg.setdefault("buttons", {})
    return cfg


def save_config(path: Path, cfg: dict) -> None:
    path.write_text(json.dumps(cfg, indent=2) + "\n")


def live_buttons(cfg: dict) -> dict:
    return {k: v for k, v in cfg["buttons"].items() if not v.get("skipped")}


def resolve(cfg: dict, name: str) -> dict:
    buttons = live_buttons(cfg)
    key = name.upper()
    if key in buttons:
        return buttons[key]
    matches = [k for k in buttons if k.startswith(key)]
    if len(matches) == 1:
        return buttons[matches[0]]
    if len(matches) > 1:
        sys.exit(f"{name!r} is ambiguous: {', '.join(sorted(matches))}")
    sys.exit(f"No button {name!r}. Try: {' '.join(sorted(buttons))}")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_list(args, cfg):
    buttons = live_buttons(cfg)
    print(f"{cfg.get('remote', 'remote')} — {len(buttons)} buttons\n")
    width = max((len(k) for k in buttons), default=8)
    for k in sorted(buttons):
        e = buttons[k]
        print(f"  {k:<{width}}  {e.get('protocol','?'):<9} "
              f"cmd 0x{int(e.get('command',0)):02X}   raw 0x{int(e['raw']):08X}")


def cmd_ports(args, cfg):
    for p in list_ports():
        print(f"  {p.device}  {p.description}")


def press(bl: Blaster, cfg: dict, name: str, repeats: int, gap: float):
    entry = resolve(cfg, name)
    resp = bl.send_raw(int(entry["raw"]), repeats)
    ok = resp.startswith("OK")
    if not bl.quiet:
        print(f"  {name.upper():<20} {'ok' if ok else 'FAILED: ' + resp}")
    if not ok and not bl.dry_run:
        return False
    time.sleep(gap)
    return True


def cmd_send(args, cfg):
    bl = Blaster(args.port, args.dry_run, args.quiet)
    try:
        for name in args.buttons:
            if not press(bl, cfg, name, args.repeat, args.gap):
                sys.exit(1)
    finally:
        bl.close()


def cmd_learn(args, cfg):
    if args.dry_run:
        sys.exit("learn needs real hardware (drop --dry-run)")
    bl = Blaster(args.port)
    try:
        key = args.name.upper()
        if key in cfg["buttons"] and not args.force:
            sys.exit(f"{key} already exists. Use --force to overwrite.")
        print(f"Learning {key} — point the remote at the receiver and press it...")
        print(bl.cmd("LEARN"))                      # "OK LEARN press a button..."
        line = bl.readline()
        if not line.startswith("LEARNED"):
            sys.exit(f"Didn't capture anything: {line or 'timeout'}")
        entry = json.loads(line[len("LEARNED"):].strip())
        if entry.get("protocol") == "UNKNOWN":
            print("  note: UNKNOWN protocol — replay may not work with sendNECRaw")
        cfg["buttons"][key] = entry
        save_config(args.config, cfg)
        print(f"  saved {key}: {entry['protocol']} raw 0x{int(entry['raw']):08X}")
        print(f"  -> {args.config}")
    finally:
        bl.close()


def cmd_mon(args, cfg):
    bl = Blaster(args.port)
    known = {int(v["raw"]): k for k, v in live_buttons(cfg).items()}
    try:
        print(bl.cmd("MON"))
        print("Watching. Ctrl-C to stop.\n")
        while True:
            line = bl.readline()
            if not line:
                continue
            if line.startswith("FRAME"):
                entry = json.loads(line[len("FRAME"):].strip())
                raw = int(entry["raw"])
                name = known.get(raw, "(unknown)")
                print(f"  0x{raw:08X}  {entry['protocol']:<9} "
                      f"cmd 0x{int(entry['command']):02X}  {name}")
            else:
                print(f"  {line}")
    except KeyboardInterrupt:
        print("\nstopping...")
        bl.cmd("x")
    finally:
        bl.close()


def cmd_repl(args, cfg):
    bl = Blaster(args.port, args.dry_run, args.quiet)
    buttons = sorted(live_buttons(cfg))
    try:
        import readline  # noqa: F401  — gives history + arrow keys for free

        def completer(text, state):
            hits = [b for b in buttons if b.startswith(text.upper())]
            return hits[state] + " " if state < len(hits) else None
        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass

    print(f"{len(buttons)} buttons. Tab completes, Ctrl-D quits.")
    print(f"  {' '.join(buttons)}\n")
    try:
        while True:
            try:
                raw = input("ir> ").strip()
            except EOFError:
                print()
                break
            if not raw:
                continue
            if raw in ("q", "quit", "exit"):
                break
            for name in raw.split():
                try:
                    press(bl, cfg, name, args.repeat, args.gap)
                except SystemExit as e:
                    print(f"  {e}")
    finally:
        bl.close()


# --------------------------------------------------------------------------- #
def main():
    # Common flags live on a parent parser so they work on either side of the
    # subcommand: `irctl.py send POWER --dry-run` and `irctl.py --dry-run send
    # POWER` are both valid.
    # SUPPRESS means an unspecified flag adds no attribute, so a value given
    # before the subcommand survives the subparser's pass.
    common = argparse.ArgumentParser(add_help=False,
                                     argument_default=argparse.SUPPRESS)
    common.add_argument("--port", help="serial port (auto-detected if omitted)")
    common.add_argument("--config", type=Path)
    common.add_argument("--dry-run", action="store_true", help="print, don't transmit")
    common.add_argument("--quiet", "-q", action="store_true")
    common.add_argument("--repeat", type=int, help="extra NEC repeat frames")
    common.add_argument("--gap", type=float, help="seconds between presses")

    DEFAULTS = {"port": None, "config": DEFAULT_CONFIG, "dry_run": False,
                "quiet": False, "repeat": 0, "gap": 0.3}

    ap = argparse.ArgumentParser(
        description="Command-line control for the DIY IR blaster.",
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  ./irctl.py send POWER\n"
               "  ./irctl.py send CW SPEED_UP SPEED_UP\n"
               "  ./irctl.py send POWER --repeat 2\n"
               "  ./irctl.py learn MUTE --config tv_codes.json\n"
               "  ./irctl.py repl")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", parents=[common], help="show buttons in the config")
    sub.add_parser("ports", parents=[common], help="list serial ports")
    sub.add_parser("mon", parents=[common], help="print every frame the receiver sees")
    sub.add_parser("repl", parents=[common], help="interactive prompt")
    p_send = sub.add_parser("send", parents=[common], help="fire one or more buttons")
    p_send.add_argument("buttons", nargs="+")
    p_learn = sub.add_parser("learn", parents=[common], help="learn a new button")
    p_learn.add_argument("name")
    p_learn.add_argument("--force", action="store_true")

    args = ap.parse_args()
    for k, v in DEFAULTS.items():
        if not hasattr(args, k):
            setattr(args, k, v)
    cfg = {"buttons": {}} if args.cmd == "ports" else load_config(args.config)
    globals()[f"cmd_{args.cmd}"](args, cfg)


if __name__ == "__main__":
    main()

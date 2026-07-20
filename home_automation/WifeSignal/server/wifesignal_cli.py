"""
WifeSignal BLE test CLI  -  toggle/read the device state from your Mac.

Install:  pip install bleak
Run:      python wifesignal_cli.py

Matches the board by its SERVICE UUID, not its name - on macOS the advertised
name is often hidden/dropped, but the service UUID is always in the packet.

Commands once connected:  on | off | toggle | read | watch | quit
"""

import asyncio
from bleak import BleakScanner, BleakClient

SVC_UUID   = "6d5f0001-4b6b-4a3a-9e1e-2a7b1c9f0001"
STATE_UUID = "6d5f0002-4b6b-4a3a-9e1e-2a7b1c9f0002"


def on_notify(_handle, data: bytearray):
    val = data[0] if data else "?"
    print(f"\n[notify] state = {val}\n> ", end="", flush=True)


async def find_device(timeout=20):
    def match(d, adv):
        return SVC_UUID.lower() in [u.lower() for u in adv.service_uuids]
    return await BleakScanner.find_device_by_filter(match, timeout=timeout)


async def main():
    print(f"scanning for service {SVC_UUID} ...")
    dev = await find_device()
    if not dev:
        print("not found - is the board powered and advertising? (serial should say 'BLE up')")
        return

    async with BleakClient(dev) as c:
        print(f"connected to {dev.address}.  commands: on | off | toggle | read | watch | quit")
        await c.start_notify(STATE_UUID, on_notify)
        loop = asyncio.get_event_loop()
        while True:
            cmd = (await loop.run_in_executor(None, input, "> ")).strip().lower()
            if cmd in ("q", "quit", "exit"):
                break
            elif cmd == "on":
                await c.write_gatt_char(STATE_UUID, bytes([1]), response=True)
            elif cmd == "off":
                await c.write_gatt_char(STATE_UUID, bytes([0]), response=True)
            elif cmd == "toggle":
                v = await c.read_gatt_char(STATE_UUID)
                cur = v[0] if v else 0
                await c.write_gatt_char(STATE_UUID, bytes([0 if cur else 1]), response=True)
            elif cmd == "read":
                v = await c.read_gatt_char(STATE_UUID)
                print(f"state = {v[0] if v else '?'}")
            elif cmd == "watch":
                print("watching for presses (Ctrl-C to stop)...")
                try:
                    while True:
                        await asyncio.sleep(1)
                except KeyboardInterrupt:
                    pass
            else:
                print("commands: on | off | toggle | read | watch | quit")


if __name__ == "__main__":
    asyncio.run(main())

"""
WifeSignal server - bridges the iPhone app (HTTP) to the ESP32-C3 lamp (BLE).

    [iPhone app] --HTTP/Bearer--> [this server] --BLE--> [ESP32-C3 lamp+button]

The app speaks 3 colors (green/yellow/red) + acknowledged; the device speaks a
single on/off byte. Mapping: any active un-acknowledged signal -> lamp ON;
clear or acknowledge -> lamp OFF. A physical button press while the lamp is on
acknowledges the signal (app shows "Seen", color is kept until cleared).

Endpoints (all JSON, Bearer auth except /health):
    POST /v1/signal  {"color": "green"|"yellow"|"red"}
    POST /v1/clear
    POST /v1/ack
    GET  /v1/status
    GET  /health     (unauthenticated, for launchd/ops health checks)

Response keys are camelCase (sentAt, acknowledgedAt) - the iOS app decodes
with a bare JSONDecoder, so snake_case would silently drop the timestamps.

Matches the board by SERVICE UUID, never by name: macOS hides advertised
names (they come back None), but the service UUID is in the advertisement.
"""

import asyncio
import contextlib
import hmac
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from aiohttp import web
from bleak import BleakClient, BleakScanner

SVC_UUID = "6d5f0001-4b6b-4a3a-9e1e-2a7b1c9f0001"
STATE_UUID = "6d5f0002-4b6b-4a3a-9e1e-2a7b1c9f0002"

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))
TOKEN = os.environ.get("SIGNAL_API_TOKEN", "")

VALID_COLORS = {"green", "yellow", "red"}
SCAN_TIMEOUT = 15
MAX_BACKOFF = 30

log = logging.getLogger("wifesignal")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class State:
    color: str | None = None
    acknowledged: bool = False
    sent_at: str | None = None
    acknowledged_at: str | None = None
    device_connected: bool = False
    # desired_lamp is the single source of truth for what the lamp should
    # show: 1 iff a signal is active and not yet acknowledged. The BLE task
    # writes it to the device; notifies are compared against it (see on_notify).
    desired_lamp: int = 0


state = State()
state_lock = asyncio.Lock()
write_needed = asyncio.Event()


def status_payload() -> dict:
    return {
        "color": state.color,
        "acknowledged": state.acknowledged,
        "sentAt": state.sent_at,
        "acknowledgedAt": state.acknowledged_at,
        "message": None if state.device_connected else "device offline",
    }


# ---------------------------------------------------------------- HTTP layer

@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.path == "/health":
        return await handler(request)
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {TOKEN}"
    if not hmac.compare_digest(auth.encode(), expected.encode()):
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def post_signal(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    color = body.get("color")
    if color not in VALID_COLORS:
        return web.json_response(
            {"error": f"color must be one of {sorted(VALID_COLORS)}"}, status=400
        )
    async with state_lock:
        state.color = color
        state.acknowledged = False
        state.sent_at = now_iso()
        state.acknowledged_at = None
        state.desired_lamp = 1
        write_needed.set()
        log.info("signal set: %s", color)
        return web.json_response(status_payload())


async def post_clear(request: web.Request) -> web.Response:
    async with state_lock:
        state.color = None
        state.acknowledged = False
        state.sent_at = None
        state.acknowledged_at = None
        state.desired_lamp = 0
        write_needed.set()
        log.info("signal cleared")
        return web.json_response(status_payload())


async def post_ack(request: web.Request) -> web.Response:
    async with state_lock:
        if state.color is not None and not state.acknowledged:
            state.acknowledged = True
            state.acknowledged_at = now_iso()
            state.desired_lamp = 0
            write_needed.set()
            log.info("signal acknowledged via /v1/ack")
        return web.json_response(status_payload())


async def get_status(request: web.Request) -> web.Response:
    async with state_lock:
        return web.json_response(status_payload())


async def get_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "deviceConnected": state.device_connected})


# ----------------------------------------------------------------- BLE layer

async def on_notify(_char, data: bytearray) -> None:
    if not data:
        return
    val = data[0]
    async with state_lock:
        if val == state.desired_lamp:
            log.debug("notify %d matches desired state (echo), ignoring", val)
            return
        if val == 0 and state.desired_lamp == 1:
            state.acknowledged = True
            state.acknowledged_at = now_iso()
            state.desired_lamp = 0
            log.info("physical button press - signal acknowledged")
            return
        # val == 1 while nothing is active: button pressed from idle. Turn it
        # back off to keep lamp == signal-active. Future "wife pings back" hook.
        log.info("idle button press - turning lamp back off")
        write_needed.set()


async def scan_for_device(timeout: float = SCAN_TIMEOUT):
    seen = 0

    def match(_d, adv):
        nonlocal seen
        seen += 1
        return SVC_UUID.lower() in [u.lower() for u in adv.service_uuids]

    dev = await BleakScanner.find_device_by_filter(match, timeout=timeout)
    return dev, seen > 0


async def wait_first(*events: asyncio.Event) -> None:
    tasks = [asyncio.create_task(e.wait()) for e in events]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()


async def ble_loop() -> None:
    backoff = 1
    while True:
        try:
            log.info("scanning for service %s ...", SVC_UUID)
            dev, saw_any = await scan_for_device()
            if dev is None:
                if not saw_any:
                    log.warning(
                        "scan saw ZERO BLE advertisements - this usually means this "
                        "process lacks Bluetooth permission. Grant it in System "
                        "Settings > Privacy & Security > Bluetooth, then restart."
                    )
                else:
                    log.info("device not found (is the board powered? serial should say 'BLE up')")
                raise ConnectionError("device not found")

            disconnected = asyncio.Event()

            def on_disconnect(_client):
                disconnected.set()

            async with BleakClient(dev, disconnected_callback=on_disconnect) as client:
                await client.start_notify(STATE_UUID, on_notify)
                async with state_lock:
                    state.device_connected = True
                    desired = state.desired_lamp
                    write_needed.clear()
                await client.write_gatt_char(STATE_UUID, bytes([desired]), response=True)
                log.info("connected to %s, lamp re-asserted to %d", dev.address, desired)
                backoff = 1

                while not disconnected.is_set():
                    await wait_first(write_needed, disconnected)
                    if disconnected.is_set():
                        break
                    if write_needed.is_set():
                        write_needed.clear()
                        async with state_lock:
                            desired = state.desired_lamp
                        await client.write_gatt_char(
                            STATE_UUID, bytes([desired]), response=True
                        )
                        log.info("wrote lamp state %d", desired)
                log.info("device disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("BLE error: %s - retrying in %ds", exc, backoff)
        async with state_lock:
            state.device_connected = False
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF)


async def ble_ctx(app: web.Application):
    task = asyncio.create_task(ble_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# ----------------------------------------------------------------------- main

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not TOKEN:
        print(
            "SIGNAL_API_TOKEN is not set. Copy .env.example to .env, generate a "
            "token with: openssl rand -hex 32",
            file=sys.stderr,
        )
        sys.exit(1)

    app = web.Application(middlewares=[auth_middleware])
    app.add_routes(
        [
            web.post("/v1/signal", post_signal),
            web.post("/v1/clear", post_clear),
            web.post("/v1/ack", post_ack),
            web.get("/v1/status", get_status),
            web.get("/health", get_health),
        ]
    )
    app.cleanup_ctx.append(ble_ctx)
    log.info("starting on %s:%d", HOST, PORT)
    web.run_app(app, host=HOST, port=PORT, print=None)


if __name__ == "__main__":
    main()

# Wife Signal

Flow: iPhone app -> HTTPS via Tailscale serve (tailnet only) -> Python server (aiohttp) on shika -> BLE (bleak) -> ESP32-C3 arcade button/lamp.

The app sends a 3-color signal (green/yellow/red). The device is a single lamp: any active signal lights it. Pressing the physical arcade button turns the lamp off and marks the signal acknowledged, which the app shows as "Seen" (color kept until the sender clears it).

## Server on shika

```bash
cd server
cp .env.example .env
openssl rand -hex 32
```

Paste the generated token into `.env` as `SIGNAL_API_TOKEN`, then:

```bash
chmod +x run.sh service.sh
./run.sh
```

Run `./run.sh` from Terminal at least once first: the initial BLE scan triggers the macOS Bluetooth permission prompt. If the log says the scan saw zero advertisements, grant Bluetooth permission in System Settings -> Privacy & Security -> Bluetooth and restart the process. This applies separately to the launchd-run copy.

Note: `pip` is broken on this machine; always use `python3 -m pip` (run.sh already does). If venv imports ever fail after a directory move, recreate it:

```bash
rm -rf .venv
python3.14 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
```

Test:

```bash
curl http://127.0.0.1:8787/health
TOKEN='paste-token'
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/v1/status
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"color":"yellow"}' http://127.0.0.1:8787/v1/signal
curl -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/v1/clear
```

## Run as a service (launchd)

```bash
cp ops/com.ariemeir.wife-signal.plist ~/Library/LaunchAgents/
ops/wife-signal up
ops/wife-signal status
ops/wife-signal logs
```

`ops/wife-signal up` bootstraps the LaunchAgent and configures Tailscale serve. `ops/wife-signal ack` acknowledges the current signal from the command line (same effect as the physical button).

## Tailscale serve

```bash
tailscale serve --bg 8787
```

The app URL is `https://shika.tailb7b217.ts.net`. This is tailnet-only (the phone must be on Tailscale); nothing is exposed to the public internet. Switch to `tailscale funnel` only if the phone needs access without Tailscale, and use a strong token if you do.

## Xcode

1. File -> New -> Project -> iOS App.
2. Product name `WifeSignal`, SwiftUI, Swift.
3. Set your Team and unique bundle ID.
4. Delete the generated app and ContentView files.
5. Drag all Swift files from `app/WifeSignal` into the target.
6. Run on your iPhone. Tap the gear and enter `https://shika.tailb7b217.ts.net` and the SIGNAL_API_TOKEN.

## Device (BLE contract)

ESP32-C3, firmware in `firmware/wifesignal_bletest.ino` (flashed and tested).

- Service UUID `6d5f0001-4b6b-4a3a-9e1e-2a7b1c9f0001`
- STATE characteristic `6d5f0002-4b6b-4a3a-9e1e-2a7b1c9f0002`, READ | WRITE | NOTIFY, 1 byte: 0x00 off, 0x01 on
- Physical button toggles state locally and notifies

The server matches the board by service UUID, never by name: macOS reports advertised names as None. `server/wifesignal_cli.py` is a standalone test CLI for the device (stop the server first; the device accepts one central at a time).

## Security

The wife-facing token can only operate this tiny API, and with tailnet-only serve it is never reachable from the public internet. If you ever switch to Funnel, generate a strong token with `openssl rand -hex 32`.

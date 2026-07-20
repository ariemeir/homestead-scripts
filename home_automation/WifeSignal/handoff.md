# WifeSignal — Handoff

Last updated: 2026-07-20

Written for someone picking up this project cold: what exists, what's been
decided (and why), what's verified working, and what's still open.

## 1. What this project is

A "traffic light" gadget for the office door. The wife taps a button in an
iPhone app; an arcade-button lamp lights up on Arie's desk; Arie presses the
arcade button to acknowledge; the app shows "Seen ✓". Full chain:

```
[iPhone app] --HTTPS (tailnet only)--> [server on shika] --BLE--> [ESP32-C3 + arcade button/lamp]
```

- The app speaks 3 colors (green/yellow/red) + acknowledged. **Today only red
  is enabled**; green/yellow are dimmed "Coming soon" (3-lamp hardware later).
- The device is a single on/off lamp. Mapping: signal active & un-acknowledged
  -> lamp ON; acknowledge/clear -> lamp OFF.
- Physical arcade press while lamp is on = acknowledge (color kept, app shows
  "Seen ✓" within one 5 s poll). Press while idle = ignored (server writes the
  lamp back off; reserved as a future "wife pings back" hook).

Machine names: **shika** = this Mac (server host, BLE central, in BLE range of
the device). **kuma** = a different Mac — early docs said the server runs
there; it does NOT. **mochi** = the iPhone (on the tailnet).

## 2. Repo layout

```
server/server.py        The whole server: aiohttp HTTP API + bleak BLE bridge, single file, single event loop
server/run.sh           Dev entry (creates venv, installs deps, sources .env, runs)
server/service.sh       launchd entry (no pip at boot)
server/.env             SIGNAL_API_TOKEN + host/port (gitignored; token currently 19072026)
server/wifesignal_cli.py  Standalone BLE test CLI (stop the server first — device accepts one central)
firmware/wifesignal_bletest.ino  ESP32-C3 firmware, flashed 2026-07-19 (see §5 lamp polarity)
app/                    SwiftUI iPhone app (xcodegen project.yml + sources)
ops/wife-signal         Manage script: up/down/restart/status/logs/ack (launchd + tailscale serve)
ops/com.ariemeir.wife-signal.plist  LaunchAgent (installed to ~/Library/LaunchAgents/)
build.sh                BROKEN legacy TestFlight pipeline — do not use (see §8)
device/esphome_example.yaml  STALE — an abandoned 3-LED Home Assistant design, does not match real hardware
```

## 3. Current deployed state (all verified 2026-07-19)

- Server runs on shika under launchd (`com.ariemeir.wife-signal`), auto-starts,
  auto-restarts, `KeepAlive` on failure.
- Exposed tailnet-only via `tailscale serve`: **https://shika.tailb7b217.ts.net**
  (valid Let's Encrypt cert). NOT a public Funnel — the phone must be on
  Tailscale. Deliberate: token is weak (`19072026`), tailnet ACLs are the wall.
- App installed on the iPhone 17 Pro Max via direct dev-signed `devicectl`
  install (no TestFlight). Polls status every 5 s; config (URL + token) is in
  the app's Settings gear and survives reinstalls.
- Full loop verified end-to-end both directions: app red -> lamp ON;
  arcade press -> lamp OFF + app "Seen ✓"; clear resets; BLE drop ->
  auto-reconnect + lamp state re-asserted.

## 4. Server design (server/server.py)

- **Why aiohttp**: bleak is asyncio; one process, one event loop, no threads.
- HTTP API (camelCase JSON — the Swift app decodes with a bare JSONDecoder, so
  snake_case keys would silently decode to nil; keep `sentAt`/`acknowledgedAt`):
  - `POST /v1/signal {"color": "green"|"yellow"|"red"}` — sets color, lamp ON
  - `POST /v1/clear` — wipes signal, lamp OFF (what the app's Clear button calls)
  - `POST /v1/ack` — acknowledge without clearing color (what `ops/wife-signal ack`
    calls; same semantics as the physical button)
  - `GET /v1/status` — polled by the app
  - `GET /health` — unauthenticated, used by launchd/ops checks; reports
    `deviceConnected`
  - Auth: `Authorization: Bearer $SIGNAL_API_TOKEN`, constant-time compare.
- Single source of truth: `desired_lamp` (1 iff signal active & un-acked).
  HTTP handlers only mutate state + set an event; one BLE task owns the
  BleakClient and does all writes.
- **Echo suppression**: after the server writes, the firmware notifies the same
  value back; the notify handler ignores any notify equal to `desired_lamp`.
  Only a notify of 0 while desired==1 counts as a physical acknowledge.
- Reconnect loop: scan by service UUID, exponential backoff 1→30 s, and on
  every (re)connect the server re-writes `desired_lamp` so the lamp can't be
  stale after a device reboot.

## 5. Device / firmware

ESP32-C3 SuperMini + arcade button (switch GPIO3, lamp GPIO6 via S8050,
onboard LED GPIO8). BLE (NimBLE): service
`6d5f0001-4b6b-4a3a-9e1e-2a7b1c9f0001`, STATE characteristic
`6d5f0002-...0002`, READ|WRITE|NOTIFY, 1 byte 0/1. Button toggles state
locally and notifies.

**Lamp polarity gotcha (bit us 2026-07-19)**: the arcade lamp circuit is wired
active-LOW (GPIO6 LOW = lamp ON), opposite to the original firmware comment.
Symptom was a fully "reversed" system (lamp on when idle, off when signaled).
The BLE contract was always correct — only the pin drive was flipped. Fixed in
`applyLED()` and re-flashed. If the lamp ever reads reversed again, check this
first, and check whether the lamp wiring was redone.

Flashing: board shows up as `/dev/cu.usbmodem*` (USB CDC).
`arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc` — the sketch
must sit in a folder named `wifesignal_bletest/`; NimBLE-Arduino lib required.
Before flashing, positively identify the board (other ESP32 projects live on
this Mac): watch serial at 115200 while toggling via the API — this firmware
prints `write -> state N`. Close any open serial monitor first (port is
exclusive). The server reconnects by itself after a flash.

## 6. Ops on shika

```
ops/wife-signal up|down|restart|status|logs|ack
```

- `up` = launchctl bootstrap + `tailscale serve --bg 8787`. Logs in
  `~/.wife-signal/logs/`.
- **TCC / Bluetooth**: macOS silently returns empty BLE scans (or hangs) when
  the process lacks Bluetooth permission. Interactive shells inherit
  Terminal's grant; the launchd python needed its own — granted via System
  Settings > Privacy & Security > Bluetooth > add
  `/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/Resources/Python.app`.
  A Homebrew python upgrade changes that path and will need re-granting.
- `restart` can fail with a launchd race right after `down`; wait 2 s and
  `up` again.
- Known machine quirks: bare `pip` is broken (always `python3 -m pip`), and
  this zsh chokes on inline `#` comments in commands.

## 7. iPhone app build & deploy (no TestFlight)

```
cd app
xcodegen generate --spec project.yml            (only needed if project.yml changed)
xcodebuild -project WifeSignal.xcodeproj -scheme WifeSignal \
  -destination 'id=<device udid>' -allowProvisioningUpdates build
xcrun devicectl device install app --device <coredevice-id> <path>/WifeSignal.app
```

- Two different device IDs: `xcodebuild` wants the hardware UDID
  (`xcrun devicectl list devices` shows the CoreDevice UUID; the UDID appears
  in xcodebuild's "Available destinations" error listing). Current phone:
  UDID `00008150-001034483EF8C01C`, CoreDevice `BE5FC5E1-952D-506B-9D97-175D146FBE4A`.
- Signing is automatic with the "Apple Development: Arie Meir" cert in the
  login keychain; `-allowProvisioningUpdates` handles device registration.
  The App Store Connect API key referenced by build.sh no longer exists and
  is not needed for this path.
- Dev-signed installs expire in ~1 year — rebuild + reinstall when the app
  stops launching.

## 8. Open items / next steps

1. **3-button hardware** — the whole point of green/yellow. When it exists:
   re-enable colors via `isAvailable` in `app/WifeSignal/Models.swift`, extend
   the firmware/BLE contract (probably one byte per color or a color byte),
   and map colors server-side.
2. **"Wife pings back"** — idle button press currently just gets written back
   off (`server.py`, notify handler). Hook exists, semantics undecided.
3. **build.sh is dead** — points at a nonexistent directory, missing API key,
   placeholder Pushover creds. Rewrite as a build+devicectl-install script or
   delete.
4. **device/esphome_example.yaml is stale** — different pins/design; delete or
   mark clearly if keeping for reference.
5. App-side polish (from 2026-07-19 code review, all non-blocking): poll
   failures after first success are swallowed; polling never pauses in
   background; token stored in UserDefaults not Keychain; raw server error
   bodies shown in UI; weak URL validation in `AppSettings.isConfigured`.
6. Consider a stronger token if this ever moves from `tailscale serve` to a
   public Funnel.

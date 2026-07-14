# ScannerCam / 3D Scanner — Handoff

Last updated: 2026-07-14

This document is written for someone picking up this project cold. It covers
what exists, what's been decided (and why), what's verified working, and
what's still open.

## 1. What this project is

A DIY tabletop photogrammetry scanner: an iPhone 12 mounted over a motorized
turntable, controlled by a Mac ("shika"), with an Arduino doing IR
pause/resume of the turntable. The iPhone runs **ScannerCam**, a from-scratch
local HTTP camera server — no cloud, no App Store, no third-party
dependencies. The full design rationale lives in
[`docs/scannercam_spec.md`](docs/scannercam_spec.md); this handoff is the
"what's actually true right now" companion to that spec.

Two machine codenames are used throughout the code/docs:
- **saru** — the iPhone (ScannerCam server)
- **shika** — the Mac (scan controller / client)

## 2. Repo layout

```
firmware/turntable_ir/     Arduino IR control (real, pre-existing, working)
capture/controller/        scan.py — turntable scan orchestration (shika side)
capture/iphone/ScannerCam/ The Xcode project (saru side) — see §4
capture/protocols/         API contract shared by both sides (api_v1.md, constants.json)
docs/scannercam_spec.md    Full technical spec, v0.2, with a revision-notes section (§19) documenting what changed from v0.1 and why
config/                    scanner.example.yaml (template) + scanner.yaml (real, gitignored, personal device/network config — never commit this)
calibration/, hardware/, reconstruction/, scans/, output/  Mostly empty scaffolding, pre-existing, untouched by this work
```

## 3. IMPORTANT: git repo structure correction

This whole `3dscanner/` tree was originally its own **separate, nested git
repo** (it had its own `.git`, independent of the outer repo). That was
wrong — the actual project repo is rooted at `/Users/ariemeir/dev/scripts`
(remote: `https://github.com/ariemeir/homestead-scripts.git`), and
`3dscanner/` is meant to live inside it as an ordinary subdirectory, not a
submodule or nested repo.

**What was done about it:** the nested `.git` inside `3dscanner/` was removed
(it contained exactly one throwaway local commit that was never pushed
anywhere, so nothing was lost) and the files were committed into the outer
`homestead-scripts` repo instead. If you see any tooling, scripts, or muscle
memory that assumes `3dscanner/` is its own git root (e.g. running `git`
commands from inside `3dscanner/` expecting it to be the toplevel), that's
now wrong — the repo root is `/Users/ariemeir/dev/scripts`.

## 4. ScannerCam iPhone app — current state

**Stack:** SwiftUI + AVFoundation + Network.framework, no third-party Swift
packages. Project is generated via **XcodeGen** from
`capture/iphone/ScannerCam/project.yml` — that file, not the checked-in
`.xcodeproj`, is the source of truth. After editing `project.yml`, run
`xcodegen generate` from that directory to regenerate the `.xcodeproj`
(both are committed for convenience, but regenerate rather than hand-editing
the `.xcodeproj`).

**Deployment specifics:**
- Bundle ID: `com.ariemeir.ScannerCam`
- Signing team: `C37565DT8L` (confirmed via the cert's OU field — automatic
  signing works out of the box on this Mac)
- Min iOS: 17.0; built/tested with Xcode 26.2, Swift 6.2.3
- **Swift language mode is pinned to 5**, not 6, deliberately — see §7.3.
- Paired device: "Arie's iPhone", iPhone 12 (iPhone13,2), UDID
  `00008101-000561193E44001E` (this is the real `devicectl` UDID; a
  different-looking `identifierForVendor`-style UUID
  `6F054B0F-6A0A-548E-9ED4-0C899AE07F65` was given earlier in the project
  brief — that one isn't used anywhere in code/config, the real UDID above
  is what matters for `xcodebuild -destination` / `devicectl`)
- Tailscale: hostname `saru`, IP `100.93.178.102` — this is the reliable way
  to reach the phone from the Mac; LAN mDNS (`saru.local`) did **not**
  resolve in testing from this Mac, unclear why, not investigated further
  (Tailscale worked fine as a fallback so it wasn't blocking)
- API port 8765, bearer token auth (token lives in Keychain + is shown/copy-
  able in Settings — **never hardcode the live token anywhere in the repo**)

**How to build/deploy without opening Xcode UI** (useful since this was all
done via CLI in this session):

```
cd capture/iphone/ScannerCam
xcodegen generate
xcodebuild -project ScannerCam.xcodeproj -scheme ScannerCam -destination "id=00008101-000561193E44001E" -configuration Debug build
```

Then find and install the built `.app`:

```
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData -maxdepth 1 -name "ScannerCam-*" | head -1)/Build/Products/Debug-iphoneos/ScannerCam.app
xcrun devicectl device install app --device 00008101-000561193E44001E "$APP_PATH"
xcrun devicectl device process launch --device 00008101-000561193E44001E com.ariemeir.ScannerCam
```

The phone must be **unlocked** for install/launch to succeed remotely
(`devicectl` will error with "device was not, or could not be, unlocked"
otherwise — there's no way around this from the CLI).

For screenshots: `idevicescreenshot` (from Homebrew's `libimobiledevice`)
needs a USB/`usbmuxd` pairing that was never set up for this device over the
network connection used this session — it did not work over the Tailscale/
wireless-only connection. If you need remote screenshots, you'll likely need
to physically connect via USB at least once and enable "Connect via network"
in Xcode's Devices window.

## 5. What's implemented and verified working

Every endpoint in the spec is implemented (not stubbed) and was tested
end-to-end against the physical device over Tailscale — real photos
captured, downloaded, and SHA-256-verified byte-for-byte on the Mac side:

- `GET /health`, `GET /status`
- `POST /captures` — full lifecycle: validation, `request_id` idempotency,
  frame-exists/overwrite semantics, storage threshold check,
  `require_locks` enforcement, real `AVCapturePhotoOutput` capture, atomic
  write, SHA-256, manifest update, `project.json` creation on first capture
- `GET /projects`, `/projects/{id}`, `/projects/{id}/manifest`,
  `/projects/{id}/images` (paginated)
- `GET`/`HEAD` `/projects/{id}/images/{frame}` (download)
- `DELETE` image / project / all-projects (with `X-Confirm-Delete`)
- `GET /storage`

On-device UI (`CameraScreen.swift`) has real controls, not just a preview:
tap-to-focus (with a reticle), Lock All/Unlock All, individual
Lock Focus/Exposure/White-Balance, exposure compensation slider, manual
focus (lens position) slider, a "Test Capture" button that fires a real
photo through the same pipeline without writing it to any project (pure
framing/focus check), and a footer showing server status, Wi-Fi IP, and
project/image counts. This was built but **only build-verified, not visually
confirmed** — the user was asked to eyeball it on-device; no screenshot was
captured (see §4 on why).

`capture/controller/scan.py` was rewritten to match the finalized API
(previously it targeted an incompatible placeholder protocol: different
port, different endpoint path, no auth, 1-based frame numbers). It now does
a health check before scanning, uses bearer auth from `--token` or
`$SCANNERCAM_TOKEN`, 0-based frames, and surfaces the API's structured JSON
error messages on failure. It still does turntable movement as an
interactive placeholder (`move_turntable_noop` — prints an instruction and
waits for Enter, or no-ops with `--non-interactive`); it does **not** yet
talk to the Arduino turntable controller (`firmware/turntable_ir/turntable.py`)
— wiring those two together is an open item (§8).

## 6. Key decisions and why

1. **Filenames are frame-only** (`frame_000034.jpg`), not
   `frame_000034_angle_170.000.jpg` as originally drafted. The angle-in-
   filename scheme broke on `overwrite: true` with a changed angle — the new
   capture would produce a different filename than the one it was supposed
   to replace, orphaning a file. Angle now only appears in the manifest and
   in the `Content-Disposition` header on download. See spec §4.4 and §19.

2. **The HTTP server has no persistent connections.** Every response sends
   `Connection: close`; the hand-rolled `HTTPServer.swift` never implements
   HTTP keep-alive or chunked transfer encoding. This was a deliberate scope
   cut to keep a from-scratch HTTP/1.1 implementation tractable — see spec
   §6.1. Clients (including `scan.py` and raw `curl`) must not assume
   connection reuse.

3. **`POST /captures` blocks the server's single request-handling thread**
   for the duration of a capture (via `DispatchSemaphore`, bridging the
   async `AVCapturePhotoOutput` callback into the synchronous route
   handler). This is called out explicitly in `CaptureRoutes.swift` — it's
   intentional, not an oversight: only one capture can run at a time anyway,
   and the server has no concurrent connection model to give up. It does
   mean `/health` or any other request will stall for ~0.5–1s during a
   capture.

4. **Swift language mode 5** (not 6) is set in `project.yml`, on purpose.
   The `NWListener`-based server and AVFoundation delegate patterns
   predate proper actor-isolation/Sendable annotations, and doing that
   migration correctly was out of scope. The toolchain is still Swift
   6.2.3 — this only relaxes strict-concurrency checking, not language
   features.

5. **XcodeGen over hand-written `.xcodeproj`.** Installed via Homebrew.
   `project.yml` is the real source of truth; the generated project files
   are committed for convenience but should be regenerated after any
   `project.yml` change, not hand-edited.

6. **Settings screen token is now actually copyable.** Originally it was
   plain `LabeledContent` text with no way to select/copy it — this
   directly caused two failed authentication attempts during testing
   because the user had to hand-transcribe a 43-character random string and
   got it wrong both times (once with an extra character, once missing a
   `-`). Fixed with `.textSelection(.enabled)` plus a "Copy Token" button
   using `UIPasteboard`. If you ever see mysterious 401s during manual
   testing, suspect a mis-copied token before suspecting the auth code.

7. **Idle timer is disabled while the server runs**
   (`UIApplication.isIdleTimerDisabled`, in `AppState.startServer`/
   `stopServer`). This was a real bug found during testing: the app is
   foreground-only by design (§11.1 of the spec), but nothing prevented iOS
   from auto-locking the screen after ~1-2 minutes of inactivity, which
   silently killed the server mid-session. This is now handled, but it's
   worth remembering that a manual power-button lock (not idle timeout)
   will still suspend the app — that's expected/documented behavior, not a
   bug.

## 7. Open items / known gaps

Roughly in priority order for a scanning rig to be genuinely usable:

1. **`scan.py` doesn't drive the real turntable yet.** It has a
   `move_turntable_noop` placeholder. `firmware/turntable_ir/turntable.py`
   (a real, working IR-remote controller talking to an Arduino Uno running
   `ir_send_gateway.ino`) exists and works standalone, but the two scripts
   aren't wired together. This is probably the single biggest thing standing
   between "API works" and "can actually run an unattended scan."
2. **No visual confirmation the new UI actually renders correctly** on
   device — build-verified only (see §5). Worth a real look before relying
   on it.
3. **UI settings screen is still mostly TODO**: image orientation picker,
   JPEG quality mode, lens selection (moot — only one lens is supported),
   "Show API examples," delete-all-projects action, and the keep-screen-
   awake / prevent-auto-lock toggle described in spec §10.3 are not
   exposed as UI (the underlying behavior — idle timer disabled while
   server runs — is implemented unconditionally, just not user-toggleable).
4. **Projects screen and Project Detail screen are stubs** — no listing,
   no delete button, no image browsing on-device. All of this works fine
   via the API (verified), just not from the UI.
5. **`require_locks: true` is now meaningfully testable** (it wasn't before
   the UI lock controls existed) but wasn't re-tested after the UI was
   added — worth a quick real check: tap Lock All, then fire a capture with
   `require_locks: true` and confirm it succeeds instead of 409ing.
6. **LAN mDNS (`saru.local`) didn't resolve** in testing; only the Tailscale
   address worked. Not root-caused. Bonjour advertisement code exists
   (`ScannerCam-saru`) but whether it's actually the mDNS issue or a Mac-
   side resolver quirk wasn't investigated.
7. **No automated tests.** Everything so far was verified via manual
   `curl` sequences against the physical device, not a test suite. There's
   an empty `capture/tests/` directory that's never been used.
8. **Post-MVP items from the spec (§18) are all still open**: ZIP project
   download, HEIC/RAW, live preview streaming, TLS, calibration capture
   mode, sharpness scoring, etc. — none of these are needed for a basic
   working scan loop, listed here only so they're not mistaken for
   oversights.

## 8. Suggested next steps

1. Visually confirm the new CameraScreen UI on-device (§7.2).
2. Wire `scan.py` to `firmware/turntable_ir/turntable.py` so a scan can
   actually run unattended: capture → IR pause → wait for settle → rotate →
   repeat.
3. Do a real multi-frame scan (aim for the 36/72-frame acceptance criteria
   in spec §17) end-to-end: `scan.py` orchestrating both the turntable and
   captures, then pull the whole project down and confirm frame count/
   ordering/hashes all check out.
4. Only after that loop works, circle back to UI polish (Projects screen,
   Settings screen) — it's not blocking the core capture workflow.

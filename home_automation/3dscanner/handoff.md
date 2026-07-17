# ScannerCam / 3D Scanner — Handoff

Last updated: 2026-07-17

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
capture/controller/        scan.py + controller/camera/turntable packages — full scan orchestration (shika side); see capture/controller/README.md
capture/iphone/ScannerCam/ The Xcode project (saru side) — see §4
capture/protocols/         API contract shared by both sides (api_v1.md, constants.json)
docs/scannercam_spec.md    Full technical spec, v0.2, with a revision-notes section (§19) documenting what changed from v0.1 and why
config/                    scanner.example.yaml (template) + scanner.yaml (real, gitignored, personal device/network config — never commit this)
reconstruction/            Photos -> mesh -> STL pipeline (Apple Object Capture); see §9 and reconstruction/README.md
calibration/, hardware/, scans/, output/  Mostly empty scaffolding, pre-existing, untouched by this work
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
- **Settings now has a "Set custom token" field** (added 2026-07-14) with a
  "Use today's date (JST)" helper — lets you set a memorable token (e.g.
  a `DDMMYYYY` date) instead of copying the 43-char random one. Takes effect live
  (auth reads the token fresh per request). Verified on-device.

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

**The full session controller is now implemented** (2026-07-14), replacing
the old flat placeholder `scan.py`. It lives in `capture/controller/` as a
proper package set — `scan.py` (CLI) plus `controller/` (config, models,
errors, state, session loop, packaging), `camera/scannercam.py` (stdlib
`urllib` ScannerCam client), and `turntable/` (interface + `noop` +
`arduino_ir`). See `capture/controller/README.md` for usage. What it does:

- Full scan loop: capture frame 0 at 0° (no move), then for each subsequent
  frame — IR start toggle → time-based rotate → stop toggle → settle →
  capture → download → SHA-256 verify — before the next move (spec §14/§15).
- **Drives the real turntable** by wrapping `firmware/turntable_ir/turntable.py`
  (the IR-code source of truth — no codes duplicated in the controller). The
  toggle is the `START_PAUSE` button; the operator pre-arms the remote to
  continuous/CW/fixed-speed, and the controller only toggles it.
- Assumed-state safety machine (spec §4/§19): stopped→running→stopped, and
  any ambiguous/interrupted toggle drops to `unknown`, which halts the
  session and demands manual realignment — it never auto-toggles out.
- Atomic `state.json`/`session.json`/`frames.json`/`checksums.sha256`,
  `diagnostics/timing.csv`, controller lock, final validation report, a
  `scans/completed/<id>/` layout with `reconstruction.json`, and a
  `output/packages/<id>.tar.gz` + `.sha256`.
- CLI subcommands: `run`, `preflight`, `resume`, `package`, `test-camera`,
  `test-turntable`, `cleanup`; exit codes per spec §29.
- **Runs in a project venv** (`.venv`, gitignored) with `requirements.txt`
  (PyYAML + pyserial + pytest); `scan.py` re-execs itself under `.venv` so
  `./capture/controller/scan.py …` works without activating it.

**Verified:** 24 pytest tests pass (`./.venv/bin/python -m pytest
capture/controller/tests`) and a full `scan.py run` was exercised end-to-end
against a local fake ScannerCam over the real urllib client + no-op turntable,
producing a valid package. **Not yet run against the physical rig** — no real
Arduino/serial or a live saru scan has been done through the new controller
(the old `scan.py` had been curl/manual-tested against saru; this rewrite has
not). See §7/§8 for what's needed before a real scan.

Two minimal, non-duplicating additions were made to
`firmware/turntable_ir/turntable.py`: a public `ping()` on the gateway classes
(so preflight can hard-verify the Arduino PONG). No IR/protocol logic was
copied out of that file.

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

1. **The new controller has never touched the physical rig.** — ✅ **RESOLVED
   2026-07-17. See §10 for the first full real-rig session.** All four
   sub-items below are done: IR emitter wired and firing, real serial port set
   (`/dev/cu.usbmodem112401`), `test-camera`/`test-turntable` both pass against
   the real hardware, and turntable speed measured (≈13.3 °/s). Kept here for
   history:
   - **Wire the IR LED emitter to the Arduino** (`firmware/turntable_ir/`) — the
     missing physical link that lets the Uno fire the turntable's `START_PAUSE`
     toggle. Done — IR reaches the table (confirmed by physical rotation).
   - **Set the real serial port** in `config/scanner.yaml` — done:
     `/dev/cu.usbmodem112401`.
   - **Run `test-turntable` and `test-camera`** against the real hardware to
     confirm the IR toggle (the LED's real test) and saru connectivity
     end-to-end. Done — both pass.
   - **Calibrate the turntable speed.** Measured: a full revolution at the
     **slowest** speed takes ~27 s → `movement.degrees_per_second: 13.3`
     (was a `12.0` guess), now set in `config/scanner.yaml`. Still nominal
     (no per-step `calibration/turntable/default.yaml` yet); the seam won't
     land exactly at 360°, but Object Capture recovers true pose from features
     so this is fine. Refine with a calibration profile later if needed.
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
6. **Server wedge — FIXED 2026-07-14.** During the first real controller run
   the whole server hung (every endpoint, including `/health`, connected but
   never responded) and had to be force-quit. Root cause was *not* the project
   routes specifically: `HTTPServer` ran the NWListener, every connection's
   I/O, *and* `router.handle` all on **one shared serial `DispatchQueue`**, and
   some handlers block it synchronously (`semaphore.wait()` in the capture
   route, `sessionQueue.sync` in the status route). One blocked handler stalled
   the listener too, so nothing — not even `/health` — could be served. Fix:
   each connection now gets its **own** serial queue (`HTTPServer.accept`), so a
   blocked request only affects itself; plus the capture `semaphore.wait()` is
   now bounded (25 s timeout) so a stalled camera can't block forever. Verified
   on-device: a 3-frame scan + hammering the previously-hung endpoints while
   pinging `/health` 5×/s → all endpoints 30–50 ms, zero `/health` failures.
   (A *second*, unrelated bug surfaced during this: the Python client's
   `list_images` assumed `offset`/`total` pagination but the API uses
   `after_frame`/`has_more`, so it looped forever re-fetching page 1 — also
   fixed, with a test.)
7. **LAN mDNS (`saru.local`) didn't resolve** in testing; only the Tailscale
   address worked. Not root-caused. Bonjour advertisement code exists
   (`ScannerCam-saru`) but whether it's actually the mDNS issue or a Mac-
   side resolver quirk wasn't investigated.
7. **App-side (Swift) has no automated tests.** The ScannerCam iPhone app was
   verified via manual `curl` sequences against the physical device, not a
   test suite. (The Python controller now *does* have a pytest suite —
   `capture/controller/tests/`, 24 tests — but the Swift side does not.)
8. **Post-MVP items from the spec (§18) are all still open**: ZIP project
   download, HEIC/RAW, live preview streaming, TLS, calibration capture
   mode, sharpness scoring, etc. — none of these are needed for a basic
   working scan loop, listed here only so they're not mistaken for
   oversights.

## 8. Suggested next steps

1. **Bring the new controller to the physical rig** (§7.1): set the real
   serial port, then `./capture/controller/scan.py test-camera` and
   `test-turntable` to confirm saru + the IR toggle work end-to-end.
2. **Calibrate turntable speed** and do a first real scan with the no-op or
   Arduino driver — start with the recommended 10°/36-frame run
   (`run --name first_real_scan --degrees 10 --settle-seconds 2`), confirm
   frame count/ordering/hashes and that steps land near 10°, then move to
   5°/72 frames.
3. Visually confirm the new CameraScreen UI on-device (§7.2) — still
   build-verified only.
4. Circle back to app UI polish (Projects screen, Settings screen) — not
   blocking the core capture workflow.

## 9. Reconstruction pipeline (photos -> mesh -> STL), added 2026-07-14

Turns `scans/completed/<id>/images/frame_*.jpg` into a 3D model, entirely on
this Mac (Apple M4). Full details in `reconstruction/README.md`.

- **COLMAP was evaluated and removed.** Its dense stereo (`patch_match_stereo`)
  is **CUDA-only** and hard-errors on Apple Silicon ("Dense stereo
  reconstruction requires CUDA"), so COLMAP could only ever give a sparse point
  cloud here — no mesh. `brew uninstall colmap` was run. COLMAP + OpenMVS only
  becomes worthwhile if you offload dense work to an NVIDIA/Linux box later.
- **Mesh stage = Apple Object Capture** (`RealityKit.PhotogrammetrySession`),
  GPU-accelerated on M-series, purpose-built for turntable capture, outputs a
  near-watertight *textured* mesh. Tool: `reconstruction/objcap/` (a ~90-line
  Swift CLI; `swift build -c release`). Wrapper:
  `reconstruction/scripts/reconstruct.sh <session_dir> [detail]` ->
  `output/meshes/<id>.usdz` (textured, single file) + `output/meshes/<id>/`
  (textured OBJ *bundle*: `baked_mesh_*.obj` + `.mtl` + textures), then
  bundle-OBJ -> STL via `assimp`.
- **NOW VERIFIED END-TO-END (2026-07-15)** on a real 171-image multi-angle set
  (RealityCapture's gingerbread sample) — `reconstruct.sh` produced a valid
  textured USDZ + OBJ bundle + STL, 169/171 frames used. This replaces the old
  "dry-run only" status; the pipeline is proven on real photogrammetry input.
  (Still **not run on our own turntable rig's** images — see §7.1.)
- **Two bugs found & fixed while verifying** (both masked by the earlier
  same-pose dry-run that failed before reaching output):
  1. **OBJ output threw `invalidOutput`.** RealityKit requires a *directory*
     URL for OBJ (it writes a bundle), and — subtly — the URL must carry
     `isDirectory: true`. Building `URL(fileURLWithPath: "foo.obj")` then
     `.deletingPathExtension()` yields a *file*-flagged URL that Object Capture
     rejects. Fixed in `objcap/main.swift` by constructing the dir URL with an
     explicit `isDirectory: true`.
  2. **STL step never found the OBJ.** `reconstruct.sh` looked for `<id>.obj`,
     but the bundle names it `baked_mesh_<hash>.obj` inside `<id>/`. Fixed to
     glob the bundle. (Also made the image-count line tolerate missing globs so
     `set -euo pipefail` doesn't abort.)
  So §9's earlier "assimp OBJ->STL confirmed" is now *actually* true.
- **Output is USDZ/OBJ (textured), not STL** — STL is a conversion step and is
  geometry-only. **Not print-watertight:** a single-ring turntable scan never
  photographs the object's underside, so the base needs a repair pass (fill
  hole, keep largest component, make manifold) before printing.
- **Repair tooling installed (2026-07-15):** MeshLab 2025.07
  (`/Applications/MeshLab2025.07.app`) and Blender 5.2
  (`/Applications/Blender.app`), both via Homebrew cask. Recommended repair
  path: prototype the recipe in MeshLab (Close Holes / Remove Isolated pieces /
  Repair non-Manifold), then script it with **PyMeshLab** as a
  `reconstruction/scripts/repair.sh`. For a *flat* printable base (vs. a bumpy
  hole-fill), Blender's bisect-at-Z-plane-and-cap is better. No `repair.sh`
  exists yet — build it against real rig geometry, not the gingerbread test.
- **NOW VERIFIED ON OUR OWN RIG (2026-07-17)** — see §10. A 72-frame turntable
  scan of a matte textured object reconstructed cleanly at `full` detail
  (87,394 triangles). The "gingerbread sample only" caveat above is retired.
- **`reconstruct.sh` re-run bug — FIXED 2026-07-17.** RealityKit's `modelFile`
  request refuses to overwrite an existing output and aborts at submit with
  `invalidOutput`, so re-running a session at a new detail level (e.g. `reduced`
  then `full`) failed. The script now `rm -rf`s the prior `$ID` outputs
  (`.usdz`/`.usda`/OBJ bundle dir/`.stl`) before running.
- **Next:** build the base-repair step (`reconstruction/scripts/repair.sh` via
  PyMeshLab) against real rig geometry — MeshLab recipe: Remove Isolated pieces
  → Close Holes → Repair non-Manifold. Optionally add a per-step turntable
  calibration profile to tighten nominal angles.

## 10. First full real-rig session (2026-07-17)

The entire chain ran end-to-end on the physical rig for the first time:
**IR arm → 36/72-frame capture → download → SHA-256 verify → package →
Object Capture → textured USDZ + STL.** ~5 minutes per capture+reconstruct loop.

**Turntable arming — important behavior discovered.** The remote must be
pre-armed to continuous/CW/slowest before a run (the controller only sends the
`START_PAUSE` toggle and assumes the table starts **stopped**). Arming is done
over IR with `firmware/turntable_ir/irctl.py`:

```
irctl.py send SPEED_DOWN SPEED_DOWN SPEED_DOWN CW ROTATE_CONTINUOUS --gap 1.0 --port /dev/cu.usbmodem112401
```

**Gotcha:** `ROTATE_CONTINUOUS` **starts the table spinning immediately** — it
is not a passive mode-select. So the arming sequence leaves the table *running*,
and you must send one `START_PAUSE` to stop it before `scan.py run`:

```
irctl.py send START_PAUSE --port /dev/cu.usbmodem112401
```

If you skip that stop, the controller (assuming STOPPED) inverts every toggle
and the whole run desyncs. `START_PAUSE` is an unreadable toggle, so confirm
visually that it actually stopped. After a `scan.py run` completes it leaves the
table armed+stopped, so back-to-back runs need no re-arming.

**Runs are launched unattended with the token inline** (it's a memorable custom
token set in ScannerCam Settings, see §4):

```
SCANNERCAM_TOKEN=<token> ./capture/controller/scan.py run --name <obj> --degrees 5 --yes
```

`--yes` skips the safety confirmation, so verify readiness first:
`test-camera` (camera authorized, session running, **focus/exposure/WB all
locked** — `require_locks: true` will reject the run otherwise) and a
`test-turntable` spin.

**Subject quality is the whole ballgame** (rig + pipeline were solid from run 1):

| Round | Subject / scene | Frames used | Result |
|-------|-----------------|-------------|--------|
| 1 | Glossy mug, cluttered desk + **monitor** behind | — | `processError` |
| 2 | Glossy mug, light tent + matte backdrop | **10/36** | partial ~90° shell |
| 3 | **Matte textured ceramic flower**, light tent | **36/36** | clean full mesh |
| 4 | Same flower, **5° / 72 frames** | **72/72** | clean; `full` = 87k tris |

Lessons: (a) a **feature-rich fixed background** (esp. a monitor showing text)
breaks the turntable solve — the object rotates but the background doesn't, and
Object Capture can't reconcile the two. Use a light tent / plain matte backdrop;
anything on the turntable disc (arrows, ruler) is fine because it rotates *with*
the object. (b) **Matte + textured + asymmetric** subjects register; **glossy +
rotationally-symmetric** ones (a ribbed mug) drop frames past ~90° because every
angle looks alike and specular highlights slide across the surface. (c) At the
slowest speed, 5° steps are ~0.26 s IR pulses and still captured reliably;
finer than that risks inconsistent rotation (motor spin-up/coast dominate).
`--degrees` must divide evenly into 360.

**Detail levels:** `reduced` decimates to a fixed ~25k-triangle target
regardless of frame count (fast sanity check); `full` on the 72-frame set gave
87,394 triangles / 19 MB STL / 49 MB textured USDZ. Extra frames pay off as
accuracy + fewer holes + sharper texture, and become real geometry at `full`.

**Config is local only** (`config/scanner.yaml` is gitignored): real serial port
`/dev/cu.usbmodem112401` and `degrees_per_second: 13.3` were set there and are
**not** in git — a fresh checkout must re-copy `scanner.example.yaml` and set
these. New firmware committed this session: `ir_blaster.ino` (learn+blast in one
sketch), `ir_smoketest.ino`, and the `irctl.py` CLI.

**Still open:** base-repair step for printing (§9); a per-step turntable
calibration profile; and a second-elevation pass (tilt) — a single-ring scan
never sees the object's top/underside, which no amount of extra frames fixes.

## 11. New scanner phone, multi-elevation capture, print-prep pipeline (2026-07-17)

### New scanner phone — iPhone 17 Pro Max
The old iPhone 12 was replaced. **ScannerCam is dev-signed, so it does NOT
transfer via iCloud/phone-migration** — it must be rebuilt from source and
side-loaded. What it took (all via CLI, paid Apple Developer account):
- New device: **iPhone 17 Pro Max**, hardware UDID `00008150-001034483EF8C01C`,
  iOS 26.5.2, 48 MP camera (images are 8064×6048 vs the 12's 4032×3024).
- **Enable Developer Mode** on the phone (Settings ▸ Privacy & Security) — iOS 16+
  requires it before Xcode can install; it only appears after the phone has been
  connected to a Mac running Xcode once. Reboot + confirm.
- Build needed **both** `-allowProvisioningUpdates` **and**
  `-allowProvisioningDeviceRegistration` for xcodebuild to auto-register the new
  device (`-allowProvisioningUpdates` alone failed with "device isn't registered").
  Full: `xcodegen generate && xcodebuild -project ScannerCam.xcodeproj -scheme
  ScannerCam -destination "id=<UDID>" -configuration Debug -allowProvisioningUpdates
  -allowProvisioningDeviceRegistration build`, then `devicectl device install app`
  + `... process launch`. On a paid account it launched with no "untrusted
  developer" trust step.
- **Networking:** new phone on Tailscale at **`100.66.118.21`** (hostname
  `iphone182`). `config/scanner.yaml` `camera.base_url` was repointed to it
  (gitignored, local only). Old phone `saru`/`100.93.178.102` is retired.
- Serial port also re-enumerated on replug to **`/dev/cu.usbmodem111401`**
  (was `...112401`) — macOS reassigns these; update `serial_port` in the config
  when it changes. Both are local/gitignored.
- On a fresh app install the token defaults to a random one — set your memorable
  custom token in ScannerCam Settings (kept out of git; it's a `DDMMYYYY`-style
  date), and re-**Lock All** each session (locks reset when the app is
  backgrounded / phone locked).

### Multi-elevation capture (rings) + combining
A single turntable ring is one camera elevation; it never sees the top/underside
well. To improve coverage you shoot **additional rings at different camera
tilts** — each ring is its own full 360° `scan.py run` (the object must NOT move
between rings; only the camera). Then **reconstruct all rings together**:
Object Capture ingests every image from every ring in one session and fuses the
poses. There is no built-in multi-ring mode yet — combine by symlinking both
sessions' `images/frame_*.jpg` into one dir with distinct prefixes
(`mid_*`, `und_*`) and running `reconstruct.sh` on that dir.
- Demonstrated: mid ring (72) + a low/under ring (72). The under ring alone
  dropped 16 near-edge-on frames (a flat disc is ambiguous edge-on); **combined
  fused 128/144** and — the real win — corrected the *thickness* (the mid ring
  over-rounded the edge it never saw; the under ring's edge-on views pinned the
  true thin profile).
- A top-down ring adds little for a flat object (redundant with the mid ring);
  more rings help *3D* objects. Real geometric detail comes from `raw` detail +
  filling the frame, not more rings.

### Detail-level timing (144 imgs @ 48 MP, on the M4)
`reduced` 6m20s / 25k tris · `full` 6m52s / 100k tris · `raw` 10m56s / **212k tris**.
Key insight: **`reduced` is barely faster than `full`** (32 s) — ~90% of runtime
is ingesting+solving the images, identical across levels; only the final
mesh/texture stage differs. So `reduced`'s value is a *lighter file*, not speed.
`raw` is the only level that adds real geometry (2.1× `full`). USDZ file size is
texture-dominated and does **not** track triangle count.

### Print-prep pipeline — `reconstruction/scripts/repair.py` (NEW, committed)
PyMeshLab tool (added to `requirements.txt`) that turns a reconstructed mesh into
a printable solid: weld → drop stray components → repair non-manifold → close
holes (**watertight**); `--normal-to-z` (orient the flat-part normal to +Z via
PCA); `--diameter-mm N` (STL is unitless, slicers read mm, so scale widest
in-plane extent to N mm → N mm print); `--smooth-base MM` (Taubin-smooth just the
bottom band to soften the fabricated base, petals untouched); then seat on Z=0
centered. Example used this session:
`repair.py in.stl out.stl --normal-to-z --diameter-mm 100 --smooth-base 3.5`
→ watertight, Z⟂flat, 100 mm flower, 17.4 mm thick.

**Object Capture already makes near-watertight meshes** — the `full`/`raw` flower
had only *one* tiny 20-edge hole; the "fabricated base" is closed topologically,
just geometrically crude (never photographed), hence `--smooth-base`.

### ⚠️ Drilling see-through holes vs. watertight (the gotcha)
Editing (crop by Z-range, delete stray verts, punch holes) is done in **Blender**
(interactive selection + Boolean modifier; MeshLab can't do booleans). Ordering
trap: **`close-holes`/`repair.py` fills EVERY open boundary, including drilled
holes that are still open**, so:
- **Drill on a clean watertight solid.** Boolean Difference through a closed solid
  yields clean tunnels that don't break watertightness; drilling a *messy* mesh
  leaves open boundaries (Blender's/headless EXACT boolean can even collapse it).
  This session: dropped the messy in-Blender drill, ran `repair.py` to get a clean
  solid, then re-drilled that.
- Blender 5.x Boolean **solvers renamed**: `Float` (old "Fast"), `Exact`,
  **`Manifold`** (new, ideal for watertight meshes — use it here). "Whole mesh
  vanishes on Difference" = flipped cutter/target normals (Shift+N, Inside off),
  Operation=Intersect, unapplied cutter scale (Ctrl+A ▸ Scale), or a
  self-intersecting joined cutter (tick Self Intersection).

**Downstream (not in repo):** the printed master is for a **one-part open-pour
silicone block mold** (flat-backed medallion → simplest case), cast in casting
gypsum (Hydrocal/dental stone > craft Plaster of Paris). Through-holes make thin
fragile mold posts — plug them for a simple first mold.

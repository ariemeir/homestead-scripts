# Scan Session Controller (`shika`)

Drives a full turntable photogrammetry session: capture a frame, rotate the
turntable by N°, settle, capture the next, download + verify every JPEG
immediately, then validate and package the set for reconstruction.

See the MVP spec for the full contract and `capture/protocols/api_v1.md` for
the ScannerCam API.

## Setup

```bash
cd /Users/ariemeir/dev/scripts/home_automation/3dscanner
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp config/scanner.example.yaml config/scanner.yaml   # then edit device details
export SCANNERCAM_TOKEN=...   # from ScannerCam Settings on saru
```

`scan.py` re-execs itself under `.venv` automatically, so `./capture/controller/scan.py …`
works without activating the venv.

## Turntable assumptions

The remote is **pre-armed** by the operator before a session: continuous mode,
clockwise, at a fixed speed. The controller only sends the `START_PAUSE` IR
toggle (start → stop). Because a toggle is not an absolute command, an
interrupted/ambiguous move leaves the state `unknown` and requires manual
intervention — the controller never auto-toggles out of it.

Angles are **nominal** (time-based, uncalibrated). Photogrammetry recovers true
pose from image features, so nominal angles are fine; add
`calibration/turntable/default.yaml` (spec §17) to override run times per step.

## Commands

```bash
./capture/controller/scan.py test-camera                       # probe ScannerCam
./capture/controller/scan.py test-turntable                    # send one start + one stop toggle
./capture/controller/scan.py preflight --name red_mug --degrees 10
./capture/controller/scan.py run       --name red_mug --degrees 10 --settle-seconds 2
./capture/controller/scan.py run       --name manual --degrees 10 --turntable noop
./capture/controller/scan.py resume    scans/incoming/<session_id>
./capture/controller/scan.py package   scans/incoming/<session_id>
./capture/controller/scan.py cleanup   <project_id>
```

`--yes` skips confirmations for unattended runs. Exit codes follow spec §29
(0 success, 3 preflight, 4 camera, 5 turntable, 6 verification, 8 resumable,
9 turntable state unknown).

## Layout

```
scan.py                 CLI entry point
controller/             config, models, errors, state, session loop, packaging
camera/scannercam.py    ScannerCam HTTP client (stdlib urllib)
turntable/              base interface + noop + arduino_ir (wraps firmware/turntable_ir)
tests/                  pytest suite (run: ./.venv/bin/python -m pytest capture/controller/tests)
```

The Arduino driver wraps `firmware/turntable_ir/turntable.py` (the source of
truth for IR codes); no IR codes are duplicated in this package.

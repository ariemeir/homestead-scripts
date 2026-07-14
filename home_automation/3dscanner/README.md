# 3D Scanner

DIY photogrammetry scanner using:

- iPhone 12 camera
- Motorized turntable
- Arduino-controlled IR pause/resume
- Photo studio light box
- Automated image capture every 5–10 degrees
- Local photogrammetry reconstruction

## Intended scan cycle

1. Start turntable.
2. Run for a calibrated duration corresponding to the desired angle.
3. Pause via Arduino IR.
4. Wait for vibration to settle.
5. Trigger the iPhone camera.
6. Confirm that the image was captured.
7. Resume the turntable.
8. Repeat until the object has completed one full rotation.

## Main areas

- `firmware/turntable_ir`: Arduino IR control.
- `capture/controller`: Scan orchestration (`shika` side — `scan.py`).
- `capture/iphone`: ScannerCam, the iPhone camera-server app (`saru` side).
- `capture/protocols`: The API contract shared by controller and app.
- `calibration/turntable`: Rotation-speed and timing calibration.
- `reconstruction`: Photogrammetry pipeline.
- `scans`: Per-object scan sessions.
- `output`: Generated point clouds, meshes, textures, and STL files.

## ScannerCam (iPhone capture app)

The iPhone runs ScannerCam, a local HTTP camera server — no cloud, no
account. The controller (`shika`) triggers captures and pulls images over
Wi-Fi or Tailscale. Full design in
[`docs/scannercam_spec.md`](docs/scannercam_spec.md); the quick-reference API
contract is in [`capture/protocols/api_v1.md`](capture/protocols/api_v1.md).

- Xcode project: `capture/iphone/ScannerCam/` (open `ScannerCam.xcodeproj`,
  or edit `project.yml` and run `xcodegen generate` to regenerate it).
- Controller: `python3 capture/controller/scan.py --name red_mug --degrees 10
  --token $SCANNERCAM_TOKEN` (token comes from ScannerCam's Settings screen).
- Copy `config/scanner.example.yaml` to `config/scanner.yaml` (gitignored)
  and fill in your device/network details.

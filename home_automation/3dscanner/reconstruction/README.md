# Reconstruction — photos → 3D model → STL

Turns a captured turntable session (`scans/completed/<id>/images/frame_*.jpg`)
into a textured mesh and a printable STL, **entirely on this Mac**.

## Why Apple Object Capture (not COLMAP) on Apple Silicon

COLMAP's dense stereo (`patch_match_stereo`) is **CUDA-only** — it hard-errors
on Apple Silicon ("Dense stereo reconstruction requires CUDA"). COLMAP would
give us only a sparse point cloud here. Apple's **Object Capture**
(`RealityKit.PhotogrammetrySession`) is GPU-accelerated on M-series, purpose-
built for object/turntable capture, and produces a near-watertight *textured
mesh* directly. So the mesh stage uses Object Capture. (If you later move to an
NVIDIA/Linux box, COLMAP + OpenMVS becomes viable for dense work.)

## Pipeline

```
scans/completed/<id>/images/frame_*.jpg
        │  reconstruction/scripts/reconstruct.sh <session_dir> [detail]
        ▼
output/meshes/<id>.usdz   textured mesh — Quick Look it (spacebar in Finder)
output/meshes/<id>.obj    textured mesh — for editing / conversion
output/meshes/<id>.stl    geometry only — for 3D printing (needs repair, below)
```

- **Detail levels:** `preview` (fast, rough) · `reduced` · `medium` (default) ·
  `full` · `raw` (slowest, densest). Start with `reduced` to sanity-check, then
  `full` for the keeper.
- **Output formats:** Object Capture writes **USDZ** and **OBJ** (textured).
  It does **not** write STL — `reconstruct.sh` converts OBJ→STL via `assimp`.
- **Watertight?** The Poisson-style surface is topologically closed, but a
  single-ring turntable scan never photographs the object's **underside**, so
  the base is fabricated/incomplete. For printing, run a repair pass: fill the
  base hole, keep the largest connected component, make it manifold — Meshlab
  (Filters ▸ Remeshing/Cleaning) or Blender's 3D-Print Toolbox.

## Build the tool (once)

```bash
cd reconstruction/objcap && swift build -c release
brew install assimp          # for the OBJ→STL step
```

`objcap` is a ~90-line Swift CLI (`reconstruction/objcap/`) wrapping
`PhotogrammetrySession`. Requires macOS 14+ and an Apple Silicon (or AMD) GPU.

## Run

```bash
./reconstruction/scripts/reconstruct.sh scans/completed/<id> full
# or drive the CLI directly:
./reconstruction/objcap/.build/release/objcap <imagesDir> medium out.usdz out.obj
```

## Capturing a *good* scan (matters more than any setting)

Object Capture needs **viewpoint diversity + overlap** — the dry-run frames
(same pose, no rotation) correctly fail with `processError`. For a real scan:

- **Object:** matte, opaque, textured, rigid, asymmetric. Avoid shiny, clear,
  or featureless surfaces.
- **Coverage:** 36–72 frames around a full turn (10° or 5° steps), each frame
  overlapping its neighbours by a lot.
- **Camera:** locked focus/exposure/white-balance (tap **Lock All** in
  ScannerCam), object filling most of the frame, stationary phone.
- **Lighting:** bright, even, diffuse; no hard moving shadows.
- Capture with `capture/controller/scan.py run --name <obj> --degrees 10`.

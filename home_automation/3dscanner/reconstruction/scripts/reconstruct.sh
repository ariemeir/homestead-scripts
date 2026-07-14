#!/usr/bin/env bash
# End-to-end reconstruction: a captured session's images -> textured mesh
# (USDZ for viewing + OBJ for editing) -> STL (geometry, for 3D printing).
#
# Usage: reconstruct.sh <session_dir> [detail]
#        detail: preview | reduced | medium | full | raw   (default: medium)
#
# STL is geometry-only and NOT guaranteed watertight — a turntable scan never
# sees the object's underside. Repair the base (fill holes, keep the largest
# component, make manifold) in Meshlab / Blender before printing.
set -euo pipefail

SESSION_DIR="${1:?usage: reconstruct.sh <session_dir> [detail]}"
DETAIL="${2:-medium}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGES="$SESSION_DIR/images"
[ -d "$IMAGES" ] || { echo "no images dir at $IMAGES" >&2; exit 1; }
ID="$(basename "$SESSION_DIR")"
OUT="$ROOT/output/meshes"
BIN="$ROOT/reconstruction/objcap/.build/release/objcap"
mkdir -p "$OUT"

if [ ! -x "$BIN" ]; then
  echo "building objcap…" >&2
  (cd "$ROOT/reconstruction/objcap" && swift build -c release >/dev/null)
fi

COUNT=$(ls "$IMAGES"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
echo "==> Object Capture: $COUNT images, detail=$DETAIL"
"$BIN" "$IMAGES" "$DETAIL" "$OUT/$ID.usdz" "$OUT/$ID.obj"

# OBJ -> STL (geometry only) if a converter is available.
if command -v assimp >/dev/null 2>&1 && [ -f "$OUT/$ID.obj" ]; then
  assimp export "$OUT/$ID.obj" "$OUT/$ID.stl" >/dev/null 2>&1 \
    && echo "STL:  $OUT/$ID.stl (repair base before printing)"
else
  echo "note: 'brew install assimp' to also emit STL, or convert $ID.obj in Meshlab."
fi

echo "Done. Outputs in $OUT:"
ls -1 "$OUT" | grep -- "$ID" || true

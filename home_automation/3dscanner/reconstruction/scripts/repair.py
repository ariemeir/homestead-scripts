#!/usr/bin/env python3
"""Make a reconstructed mesh printable: seal it watertight, orient it, scale it.

A single-ring (or multi-ring) turntable scan comes out of Object Capture as a
near-closed surface with a fabricated, often-open base. This turns that into a
clean, watertight, correctly-oriented, real-world-sized solid ready to slice.

Steps (each optional except the repair):
  1. weld + drop stray components + repair non-manifold + close holes -> watertight
  2. --normal-to-z : rotate so the object's flattest axis (its normal) is +Z
  3. --diameter-mm : uniformly scale so the widest in-plane extent is N mm
                     (STL has no units; slicers read mm, so N mm -> N mm print)
  4. --smooth-base MM : Taubin-smooth just the bottom MM band (softens the
                        fabricated base without touching the detailed top)
  5. sit the result on Z=0, centered in XY (bed-ready)

Usage:
  ./repair.py in.stl out.stl --normal-to-z --diameter-mm 100 --smooth-base 3.5

Requires: pip install pymeshlab   (pulls in numpy)

NOTE ON DRILLED HOLES: close-holes fills *every* open boundary, so if you drilled
see-through holes that are still open boundaries (not clean tunnels), this will
seal them. Drill on the watertight output instead, or make the holes real tunnels
first. See handoff.md §11.
"""
from __future__ import annotations
import argparse
import sys

import numpy as np
import pymeshlab as ml


def repair_watertight(ms: ml.MeshSet) -> dict:
    ms.meshing_remove_duplicate_vertices()
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_unreferenced_vertices()
    tf = ms.current_mesh().face_number()
    ms.meshing_remove_connected_component_by_face_number(mincomponentsize=max(1000, tf // 4))
    for _ in range(2):
        ms.meshing_repair_non_manifold_edges()
        ms.meshing_repair_non_manifold_vertices()
        ms.meshing_close_holes(maxholesize=1000000, selfintersection=False)
    return ms.get_topological_measures()


def orient_normal_to_z(ms: ml.MeshSet) -> None:
    """Rotate so the smallest principal axis (the flat-part normal) becomes +Z."""
    m = ms.current_mesh()
    V = m.vertex_matrix().copy()
    c = V.mean(0)
    _, vec = np.linalg.eigh((V - c).T @ (V - c) / len(V))  # cols ascending by eigenvalue
    R = np.stack([vec[:, 2], vec[:, 1], vec[:, 0]], 0)      # large->X, mid->Y, small(normal)->Z
    if np.linalg.det(R) < 0:
        R[1] *= -1
    _replace(ms, (V - c) @ R.T, m.face_matrix())


def scale_and_seat(ms: ml.MeshSet, diameter_mm: float | None) -> np.ndarray:
    m = ms.current_mesh()
    V = m.vertex_matrix().copy()
    if diameter_mm:
        ext = V.max(0) - V.min(0)
        V *= diameter_mm / max(ext[0], ext[1])
    V[:, 0] -= (V[:, 0].max() + V[:, 0].min()) / 2
    V[:, 1] -= (V[:, 1].max() + V[:, 1].min()) / 2
    V[:, 2] -= V[:, 2].min()
    _replace(ms, V, m.face_matrix())
    return V.max(0) - V.min(0)


def smooth_base(ms: ml.MeshSet, band_mm: float) -> int:
    ms.compute_selection_by_condition_per_vertex(condselect=f"z < {band_mm}")
    n = ms.current_mesh().selected_vertex_number()
    if n:
        ms.apply_coord_taubin_smoothing(stepsmoothnum=12, lambda_=0.5, mu=-0.53, selected=True)
    return n


def _replace(ms: ml.MeshSet, V: np.ndarray, F: np.ndarray) -> None:
    ms.add_mesh(ml.Mesh(vertex_matrix=V, face_matrix=F))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--normal-to-z", action="store_true", help="orient flat-part normal to +Z")
    ap.add_argument("--diameter-mm", type=float, default=None, help="scale widest in-plane extent to N mm")
    ap.add_argument("--smooth-base", type=float, default=None, metavar="MM", help="Taubin-smooth the bottom MM band")
    args = ap.parse_args()

    ms = ml.MeshSet()
    ms.load_new_mesh(args.input)
    tm = repair_watertight(ms)
    print(f"repaired: boundary_edges={tm.get('boundary_edges')} "
          f"non_manifold={tm.get('non_two_manifold_edges')} "
          f"components={tm.get('connected_components_number')} "
          f"watertight={tm.get('boundary_edges') == 0}")
    if args.normal_to_z:
        orient_normal_to_z(ms)
    # scale + seat first, so the base band below is measured in real mm
    ext = scale_and_seat(ms, args.diameter_mm)
    if args.smooth_base:
        print(f"smoothed {smooth_base(ms, args.smooth_base):,} base vertices (z < {args.smooth_base} mm)")
        ext = scale_and_seat(ms, None)  # re-seat on Z=0 after smoothing nudged the base
    print(f"final bbox (mm): X={ext[0]:.1f} Y={ext[1]:.1f} Z={ext[2]:.1f}")
    ms.save_current_mesh(args.output)
    print(f"saved: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

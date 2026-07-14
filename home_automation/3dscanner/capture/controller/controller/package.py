"""Final validation, the completed-session layout, and the reconstruction archive.

Covers spec §23 (final validation), §24 (completed directory + archive), and
§25 (reconstruction.json). JPEG integrity here is structural (SOI/EOI markers)
and hash-based; SHA-256 equivalence with ScannerCam is asserted at download
time in the session loop.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
from pathlib import Path

from .errors import PackagingError
from .models import SCHEMA_VERSION, AssumedState, CapturePlan, FrameRecord
from .state import SessionLayout, atomic_write_json, atomic_write_text

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


def is_valid_jpeg(path: Path) -> bool:
    """Structural check: begins with SOI and ends with EOI (spec §15, §23)."""
    try:
        size = path.stat().st_size
        if size < 4:
            return False
        with open(path, "rb") as handle:
            if handle.read(2) != JPEG_SOI:
                return False
            handle.seek(-2, 2)
            return handle.read(2) == JPEG_EOI
    except OSError:
        return False


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


# --- final validation (spec §23) ------------------------------------------- #
def build_validation_report(
    plan: CapturePlan,
    layout: SessionLayout,
    frames: list[FrameRecord],
    remote_frame_count: int | None,
    assumed_state: str,
    camera_reachable: bool,
) -> dict:
    expected = plan.frame_count
    frames_by_index = {f.frame: f for f in frames}

    local_frames = []
    invalid_jpegs = []
    hash_mismatches = []
    for frame in range(expected):
        path = layout.image_path(frame)
        if not path.exists():
            continue
        local_frames.append(frame)
        if not is_valid_jpeg(path):
            invalid_jpegs.append(frame)
            continue
        record = frames_by_index.get(frame)
        if record and record.sha256 and sha256_file(path) != record.sha256:
            hash_mismatches.append(frame)

    missing = [f for f in range(expected) if f not in local_frames]
    part_files = sorted(p.name for p in layout.images.glob(".frame_*.part"))
    verified_hashes = len(local_frames) - len(invalid_jpegs) - len(hash_mismatches)

    # camera reachability is informational, not a hard gate: each frame was
    # already SHA-256-verified against the server at download time, so local
    # integrity implies remote fidelity even if the phone is unreachable now.
    # A remote count is only enforced when we actually obtained one.
    passed = (
        len(local_frames) == expected
        and not missing
        and not invalid_jpegs
        and not hash_mismatches
        and not part_files
        and (remote_frame_count is None or remote_frame_count == expected)
        and assumed_state == AssumedState.STOPPED
    )

    report = {
        "status": "passed" if passed else "failed",
        "expected_frames": expected,
        "local_frames": len(local_frames),
        "remote_frames": remote_frame_count,
        "verified_hashes": verified_hashes,
        "missing_frames": missing,
        "invalid_jpegs": invalid_jpegs,
        "hash_mismatches": hash_mismatches,
        "pending_part_files": part_files,
        "turntable_assumed_state": assumed_state,
        "camera_reachable": camera_reachable,
    }
    atomic_write_json(layout.metadata / "validation_report.json", report)
    return report


# --- reconstruction metadata (spec §25) ------------------------------------ #
def build_reconstruction_json(
    session_id: str, plan: CapturePlan, frames: list[FrameRecord], camera_locked: bool
) -> dict:
    dims = next(((f.width, f.height) for f in frames if f.width and f.height), (None, None))
    return {
        "schema_version": SCHEMA_VERSION,
        "scan_id": session_id,
        "image_directory": "images",
        "image_pattern": "frame_*.jpg",
        "image_count": len(frames),
        "capture_type": "turntable_single_ring",
        "rotation": {
            "direction": "clockwise",
            "degrees_per_frame": plan.degrees_per_frame,
            "first_angle_degrees": plan.first_angle_degrees,
            "last_angle_degrees": plan.last_angle_degrees,
        },
        "camera": {
            "device": "iPhone 12",
            "lens": "rear_wide_1x",
            "camera_stationary": True,
            "focus_locked": camera_locked,
            "exposure_locked": camera_locked,
            "white_balance_locked": camera_locked,
            "image_width": dims[0],
            "image_height": dims[1],
        },
        "turntable": {
            "control_type": "single_ir_toggle_start_stop",
            "object_rotates": True,
        },
    }


_README = """3D Scanner turntable capture — {session_id}

Images:    images/frame_000000.jpg ... ({count} frames, {step:g}deg steps)
Order:     zero-based frame index == capture order == increasing angle
Camera:    iPhone (stationary); object rotates clockwise on the turntable
Ingest:    feed images/frame_*.jpg to your photogrammetry pipeline
Metadata:  metadata/reconstruction.json, metadata/frames.json
Integrity: metadata/checksums.sha256, metadata/validation_report.json
"""


def build_completed_directory(
    incoming: SessionLayout,
    completed_root: Path,
    session_id: str,
    plan: CapturePlan,
    frames: list[FrameRecord],
    camera_locked: bool,
) -> SessionLayout:
    """Move the session into scans/completed and add reconstruction outputs."""
    dest_root = completed_root / session_id
    if dest_root.exists():
        raise PackagingError(f"Completed directory already exists: {dest_root}")
    dest_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(incoming.root), str(dest_root))

    completed = SessionLayout(dest_root)
    atomic_write_json(
        completed.metadata / "reconstruction.json",
        build_reconstruction_json(session_id, plan, frames, camera_locked),
    )
    atomic_write_text(
        dest_root / "README.txt",
        _README.format(
            session_id=session_id,
            count=len(frames),
            step=plan.degrees_per_frame,
        ),
    )
    return completed


# --- archive (spec §24) ---------------------------------------------------- #
def create_archive(
    completed: SessionLayout,
    packages_root: Path,
    session_id: str,
    package_format: str = "tar.gz",
) -> tuple[Path, Path]:
    if package_format != "tar.gz":
        raise PackagingError(f"Unsupported package_format: {package_format!r}")
    packages_root.mkdir(parents=True, exist_ok=True)
    archive_path = packages_root / f"{session_id}.tar.gz"

    with tarfile.open(archive_path, "w:gz") as tar:
        # Top-level folder inside the archive == session_id (spec §24).
        tar.add(str(completed.root), arcname=session_id)

    # Verify the archive is readable and contains the images (spec §26).
    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
    if not any(n.startswith(f"{session_id}/images/frame_") for n in names):
        raise PackagingError(f"Archive {archive_path} contains no images.")

    digest = sha256_file(archive_path)
    sha_path = archive_path.with_name(archive_path.name + ".sha256")
    atomic_write_text(sha_path, f"{digest}  {archive_path.name}\n")
    return archive_path, sha_path

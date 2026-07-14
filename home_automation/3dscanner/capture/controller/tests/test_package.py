"""Validation, reconstruction metadata, and archive creation (spec §23–§25)."""

import hashlib
import tarfile

import pytest

from controller import package as pkg
from controller.models import AssumedState, CapturePlan, FrameRecord
from controller.state import SessionLayout

JPEG = b"\xff\xd8" + b"\x00" * 64 + b"\xff\xd9"


def _write_frame(layout, frame):
    layout.image_path(frame).write_bytes(JPEG)
    return FrameRecord(
        frame=frame,
        angle_degrees=frame * 90.0,
        filename=f"frame_{frame:06d}.jpg",
        sha256=hashlib.sha256(JPEG).hexdigest(),
        size_bytes=len(JPEG),
        width=4032,
        height=3024,
    )


def _layout(tmp_path):
    layout = SessionLayout(tmp_path / "sess")
    layout.create_skeleton()
    return layout


def test_is_valid_jpeg(tmp_path):
    good = tmp_path / "good.jpg"
    good.write_bytes(JPEG)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a jpeg at all")
    assert pkg.is_valid_jpeg(good)
    assert not pkg.is_valid_jpeg(bad)


def test_validation_passes(tmp_path):
    layout = _layout(tmp_path)
    plan = CapturePlan.from_step(90, 0.0)  # 4 frames
    frames = [_write_frame(layout, f) for f in range(4)]
    report = pkg.build_validation_report(
        plan, layout, frames, remote_frame_count=4,
        assumed_state=AssumedState.STOPPED, camera_reachable=True,
    )
    assert report["status"] == "passed"
    assert report["local_frames"] == 4
    assert report["missing_frames"] == []
    assert (layout.metadata / "validation_report.json").exists()


def test_validation_fails_on_missing_and_unknown_state(tmp_path):
    layout = _layout(tmp_path)
    plan = CapturePlan.from_step(90, 0.0)
    frames = [_write_frame(layout, f) for f in range(3)]  # missing frame 3
    report = pkg.build_validation_report(
        plan, layout, frames, remote_frame_count=3,
        assumed_state=AssumedState.UNKNOWN, camera_reachable=True,
    )
    assert report["status"] == "failed"
    assert report["missing_frames"] == [3]


def test_validation_flags_part_files(tmp_path):
    layout = _layout(tmp_path)
    plan = CapturePlan.from_step(90, 0.0)
    frames = [_write_frame(layout, f) for f in range(4)]
    layout.image_part(4).write_bytes(b"partial")
    report = pkg.build_validation_report(
        plan, layout, frames, remote_frame_count=4,
        assumed_state=AssumedState.STOPPED, camera_reachable=True,
    )
    assert report["status"] == "failed"
    assert report["pending_part_files"]


def test_build_completed_and_archive(tmp_path):
    layout = _layout(tmp_path)
    plan = CapturePlan.from_step(90, 0.0)
    frames = [_write_frame(layout, f) for f in range(4)]
    layout.session_json.write_text("{}")

    completed = pkg.build_completed_directory(
        layout, tmp_path / "completed", "20260714-000000-mug", plan, frames, True
    )
    assert (completed.root / "README.txt").exists()
    assert (completed.metadata / "reconstruction.json").exists()

    archive, sha = pkg.create_archive(
        completed, tmp_path / "packages", "20260714-000000-mug"
    )
    assert archive.exists() and sha.exists()
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "20260714-000000-mug/images/frame_000000.jpg" in names
    # Checksum file matches the archive.
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest in sha.read_text()


def test_reconstruction_json_shape():
    plan = CapturePlan.from_step(5, 2.0)
    frames = [
        FrameRecord(0, 0.0, "frame_000000.jpg", "abc", 100, width=4032, height=3024)
    ]
    doc = pkg.build_reconstruction_json("scan1", plan, frames, camera_locked=True)
    assert doc["rotation"]["degrees_per_frame"] == 5.0
    assert doc["rotation"]["direction"] == "clockwise"
    assert doc["image_count"] == 1
    assert doc["camera"]["focus_locked"] is True

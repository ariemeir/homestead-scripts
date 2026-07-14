"""End-to-end session loop with a fake camera + no-op turntable (spec §14, §23)."""

import hashlib

import pytest

from controller.config import (
    CameraConfig,
    CaptureConfig,
    Config,
    MovementConfig,
    SessionConfig,
    TurntableConfig,
)
from controller.models import CapturePlan, make_session_id
from controller.session import SessionController
from controller.state import ControllerLock, SessionLayout, StateStore
from turntable.noop import NoOpTurntableController

JPEG = b"\xff\xd8" + b"\x00" * 200 + b"\xff\xd9"
JPEG_SHA = hashlib.sha256(JPEG).hexdigest()


class FakeCamera:
    base_url = "http://fake/api/v1"

    def __init__(self):
        self.captured = set()
        self.capture_calls = 0

    def health(self):
        return {"status": "ok", "version": "0.1.0"}

    def status(self):
        locked = {"mode": "locked", "adjusting": False}
        return {
            "status": "ready",
            "capture_in_progress": False,
            "camera": {
                "authorized": True,
                "session_running": True,
                "focus": locked,
                "exposure": locked,
                "white_balance": locked,
            },
            "storage": {"free_bytes": 40_000_000_000, "image_count": len(self.captured)},
        }

    def storage(self):
        return self.status()["storage"]

    def capture(self, project_id, frame, angle_degrees, request_id, require_locks, overwrite=False):
        self.capture_calls += 1
        self.captured.add(frame)
        return {
            "status": "captured",
            "frame": frame,
            "filename": f"frame_{frame:06d}.jpg",
            "sha256": JPEG_SHA,
            "size_bytes": len(JPEG),
            "width": 4032,
            "height": 3024,
            "captured_at": "2026-07-14T00:00:00+09:00",
        }

    def download_image(self, project_id, frame, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(JPEG)
        return {
            "content_type": "image/jpeg",
            "size_bytes": len(JPEG),
            "declared_size_bytes": len(JPEG),
            "server_sha256": JPEG_SHA,
            "local_sha256": JPEG_SHA,
        }

    def head_image(self, project_id, frame):
        return {"size_bytes": len(JPEG), "sha256": JPEG_SHA, "content_type": "image/jpeg"}

    def list_images(self, project_id):
        return [{"frame": f} for f in sorted(self.captured)]

    def get_manifest(self, project_id):
        return {"project_id": project_id, "frames": sorted(self.captured)}

    def delete_project(self, project_id):
        self.deleted = project_id


def make_config(tmp_path):
    src = tmp_path / "scanner.yaml"
    src.write_text("scanner:\n  name: test\n")
    return Config(
        scanner_name="test",
        camera=CameraConfig(base_url="http://fake/api/v1", require_locks=True),
        turntable=TurntableConfig(driver="noop", movement=MovementConfig()),
        capture=CaptureConfig(
            degrees_per_frame=90,
            settle_seconds=0.0,
            initial_settle_seconds=0.0,
            retry_delay_seconds=0.0,
        ),
        session=SessionConfig(
            scans_root=tmp_path / "incoming",
            completed_root=tmp_path / "completed",
            failed_root=tmp_path / "failed",
            packages_root=tmp_path / "packages",
        ),
        calibration=None,
        source_path=src,
        raw={},
    )


def make_controller(tmp_path, camera, *, config=None, session_id=None, do_init=True):
    config = config or make_config(tmp_path)
    session_id = session_id or make_session_id("mug")
    layout = SessionLayout(config.session.scans_root / session_id)
    layout.create_skeleton()
    plan = CapturePlan.from_step(config.capture.degrees_per_frame, config.capture.settle_seconds)
    turntable = NoOpTurntableController(interactive=False, clock=lambda: "T")
    store = StateStore(layout)
    lock = ControllerLock(config.session.scans_root.parent / ".controller.lock", session_id)
    controller = SessionController(
        config=config,
        session_id=session_id,
        display_name="mug",
        plan=plan,
        camera=camera,
        turntable=turntable,
        layout=layout,
        store=store,
        lock=lock,
        require_locks=True,
        assume_yes=True,
        interactive=False,
        sleep=lambda s: None,
        prompt=lambda m: "",
    )
    if do_init:
        controller.init_state()
    return controller, config, session_id


def test_full_session_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("SCANNERCAM_TOKEN", "tok")
    camera = FakeCamera()
    controller, config, session_id = make_controller(tmp_path, camera)

    rc = controller.run()

    assert rc == 0
    assert camera.capture_calls == 4  # 90° step -> 4 frames
    completed = config.session.completed_root / session_id
    assert completed.exists()
    assert (completed / "images" / "frame_000000.jpg").exists()
    assert (completed / "images" / "frame_000003.jpg").exists()
    assert (config.session.packages_root / f"{session_id}.tar.gz").exists()
    assert (config.session.packages_root / f"{session_id}.tar.gz.sha256").exists()

    report = _read_json(completed / "metadata" / "validation_report.json")
    assert report["status"] == "passed"
    assert report["local_frames"] == 4

    frames = _read_json(completed / "metadata" / "frames.json")["frames"]
    assert len(frames) == 4
    assert [f["frame"] for f in frames] == [0, 1, 2, 3]


def test_first_frame_captured_before_any_move(tmp_path, monkeypatch):
    """Frame 0 must be captured at 0° with no rotation (spec §3, acceptance #6)."""
    monkeypatch.setenv("SCANNERCAM_TOKEN", "tok")
    camera = FakeCamera()
    controller, config, session_id = make_controller(tmp_path, camera)

    moves = []
    original = controller.turntable.move_by_degrees

    def spy(degrees, run_seconds=None):
        moves.append(("move", len(camera.captured)))
        return original(degrees, run_seconds)

    controller.turntable.move_by_degrees = spy
    controller.run()

    # The first move only happens after frame 0 is already captured.
    assert moves[0][1] >= 1


def test_hash_mismatch_fails_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("SCANNERCAM_TOKEN", "tok")

    class BadCamera(FakeCamera):
        def download_image(self, project_id, frame, destination):
            destination.write_bytes(b"\xff\xd8corrupt\xff\xd9")
            return {
                "content_type": "image/jpeg",
                "size_bytes": 11,
                "declared_size_bytes": 11,
                "server_sha256": "deadbeef",
                "local_sha256": hashlib.sha256(b"\xff\xd8corrupt\xff\xd9").hexdigest(),
            }

    camera = BadCamera()
    controller, config, session_id = make_controller(tmp_path, camera)
    from controller.errors import VerificationError

    with pytest.raises(VerificationError):
        controller.run()


def test_resume_completes_remaining_frames(tmp_path, monkeypatch):
    """A session with only frame 0 captured resumes and finishes (acceptance #13)."""
    monkeypatch.setenv("SCANNERCAM_TOKEN", "tok")
    camera = FakeCamera()
    config = make_config(tmp_path)

    # Partial session: write manifest/state and capture frame 0 only.
    first, _, session_id = make_controller(tmp_path, camera, config=config)
    first.write_session_manifest()
    first.capture_and_pull(0, 0.0)
    assert (config.session.scans_root / session_id / "images" / "frame_000000.jpg").exists()

    # Fresh controller over the same directory resumes.
    resumed, _, _ = make_controller(
        tmp_path, camera, config=config, session_id=session_id, do_init=False
    )
    rc = resumed.resume()

    assert rc == 0
    assert camera.capture_calls == 4  # frame 0 + resumed 1,2,3
    completed = config.session.completed_root / session_id
    report = _read_json(completed / "metadata" / "validation_report.json")
    assert report["status"] == "passed"


def _read_json(path):
    import json

    return json.loads(path.read_text())

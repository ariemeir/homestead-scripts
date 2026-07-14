"""ScannerCam client against a canned local HTTP server (spec §7, §20)."""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from camera.scannercam import ScannerCamClient, _server_sha
from controller.errors import CameraError

JPEG = b"\xff\xd8" + b"\x00" * 128 + b"\xff\xd9"
JPEG_SHA = hashlib.sha256(JPEG).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/api/v1/health":
            return self._json(200, {"status": "ok", "version": "0.1.0"})
        if self.path.endswith("/images/0"):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(JPEG)))
            self.send_header("X-ScannerCam-SHA256", JPEG_SHA)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(JPEG)
            return
        return self._json(404, {"error": {"code": "not_found", "message": "nope"}})

    def do_HEAD(self):
        if self.path.endswith("/images/0"):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(JPEG)))
            self.send_header("X-ScannerCam-SHA256", JPEG_SHA)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        if body.get("frame") == 999:
            return self._json(
                401, {"error": {"code": "unauthorized", "message": "bad token"}}
            )
        return self._json(
            201,
            {
                "status": "captured",
                "frame": body["frame"],
                "filename": f"frame_{body['frame']:06d}.jpg",
                "sha256": JPEG_SHA,
                "size_bytes": len(JPEG),
                "width": 4032,
                "height": 3024,
            },
        )


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}/api/v1"
    httpd.shutdown()


def _client(base):
    return ScannerCamClient(base, token="tok")


def test_health(server):
    assert _client(server).health()["status"] == "ok"


def test_capture(server):
    result = _client(server).capture("proj", 5, 25.0, "req-5", require_locks=True)
    assert result["status"] == "captured"
    assert result["sha256"] == JPEG_SHA


def test_capture_unauthorized_is_terminal(server):
    with pytest.raises(CameraError) as exc:
        _client(server).capture("proj", 999, 0.0, "req", require_locks=True)
    assert exc.value.retryable is False
    assert exc.value.code == "unauthorized"


def test_download_and_hash(server, tmp_path):
    dest = tmp_path / "frame.jpg"
    dl = _client(server).download_image("proj", 0, dest)
    assert dl["content_type"] == "image/jpeg"
    assert dl["local_sha256"] == JPEG_SHA
    assert dl["server_sha256"] == JPEG_SHA
    assert dl["size_bytes"] == len(JPEG)
    assert dest.read_bytes() == JPEG


def test_head_image(server):
    head = _client(server).head_image("proj", 0)
    assert head["size_bytes"] == len(JPEG)
    assert head["sha256"] == JPEG_SHA


def test_missing_token_raises():
    with pytest.raises(CameraError):
        ScannerCamClient("http://x/api/v1", token=None).status()


def test_server_sha_prefers_header_then_etag():
    assert _server_sha({"X-ScannerCam-SHA256": "ABC"}) == "abc"
    assert _server_sha({"ETag": '"def"'}) == "def"
    assert _server_sha({}) is None

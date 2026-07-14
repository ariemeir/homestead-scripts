"""ScannerCam API v1 client (spec §7; contract in capture/protocols/api_v1.md).

Pure stdlib (``urllib``). Every call is an independent request — ScannerCam
sends ``Connection: close`` and closes the socket, so there is nothing to pool.
Errors are translated into :class:`CameraError` with a ``retryable`` flag the
session's retry loop consults (spec §20).
"""

from __future__ import annotations

import hashlib
import http.client
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

from controller.errors import CameraError

# ScannerCam error codes that represent transient faults worth retrying.
_RETRYABLE_CODES = {"capture_in_progress", "capture_failed", "file_write_failed"}
# Codes that are terminal — retrying cannot help (spec §20 "Do not retry").
_TERMINAL_CODES = {
    "unauthorized",
    "invalid_request",
    "invalid_project_id",
    "invalid_frame",
    "invalid_angle",
    "camera_not_locked",
    "insufficient_storage",
    "not_found",
}

_CHUNK = 64 * 1024


class ScannerCamClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        connect_timeout: float = 5.0,
        capture_timeout: float = 30.0,
        download_timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.connect_timeout = connect_timeout
        self.capture_timeout = capture_timeout
        self.download_timeout = download_timeout

    # -- low-level ---------------------------------------------------------- #
    def _headers(self, auth: bool = True, extra: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if auth:
            if not self.token:
                raise CameraError(
                    "No ScannerCam bearer token available.", retryable=False
                )
            headers["Authorization"] = f"Bearer {self.token}"
        if extra:
            headers.update(extra)
        return headers

    def _open(self, request: urllib.request.Request, timeout: float):
        """Open a request, normalising transport/HTTP failures to CameraError."""
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            code = None
            message = body
            try:
                envelope = json.loads(body).get("error", {})
                code = envelope.get("code")
                message = envelope.get("message", body)
            except (json.JSONDecodeError, AttributeError):
                pass
            retryable = self._is_retryable(exc.code, code)
            raise CameraError(
                f"ScannerCam {request.method} {request.full_url} -> "
                f"HTTP {exc.code} {code or ''}: {message}".strip(),
                retryable=retryable,
                code=code,
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            # DNS/connection/timeouts — transient by nature.
            raise CameraError(
                f"Could not reach ScannerCam ({request.method} "
                f"{request.full_url}): {exc.reason}",
                retryable=True,
            ) from exc
        except (TimeoutError, socket.timeout, ConnectionError, http.client.HTTPException) as exc:
            # A bare socket timeout or dropped `Connection: close` socket during
            # getresponse() is NOT a URLError subclass, so it would otherwise
            # escape unwrapped. Treat all as transient/retryable.
            raise CameraError(
                f"ScannerCam transport error ({request.method} "
                f"{request.full_url}): {exc!r}",
                retryable=True,
            ) from exc

    @staticmethod
    def _is_retryable(status: int, code: str | None) -> bool:
        if code in _TERMINAL_CODES:
            return False
        if code in _RETRYABLE_CODES:
            return True
        if code == "frame_exists":
            return False  # handled explicitly by the caller
        if status in (408, 425, 429, 500, 502, 503, 504):
            return True
        if status == 423:  # camera_unavailable — usually transient
            return True
        return False

    def _get_json(self, path: str, *, auth: bool = True, timeout: float | None = None) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}", headers=self._headers(auth), method="GET"
        )
        with self._open(request, timeout or self.connect_timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    # -- status endpoints (spec §13) --------------------------------------- #
    def health(self) -> dict:
        return self._get_json("/health", auth=False)

    def status(self) -> dict:
        return self._get_json("/status")

    def storage(self) -> dict:
        return self._get_json("/storage")

    # -- capture (spec §15, §16) ------------------------------------------- #
    def capture(
        self,
        project_id: str,
        frame: int,
        angle_degrees: float,
        request_id: str,
        require_locks: bool,
        overwrite: bool = False,
    ) -> dict:
        payload = {
            "project_id": project_id,
            "frame": frame,
            "angle_degrees": angle_degrees,
            "overwrite": overwrite,
            "require_locks": require_locks,
            "request_id": request_id,
        }
        request = urllib.request.Request(
            f"{self.base_url}/captures",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(extra={"Content-Type": "application/json"}),
            method="POST",
        )
        with self._open(request, self.capture_timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    # -- images ------------------------------------------------------------ #
    def head_image(self, project_id: str, frame: int) -> dict:
        """Size + SHA-256 of a remote image without downloading the body."""
        request = urllib.request.Request(
            f"{self.base_url}/projects/{project_id}/images/{frame}",
            headers=self._headers(),
            method="HEAD",
        )
        with self._open(request, self.connect_timeout) as response:
            headers = response.headers
            return {
                "size_bytes": _int_or_none(headers.get("Content-Length")),
                "sha256": _server_sha(headers),
                "content_type": headers.get("Content-Type"),
            }

    def download_image(self, project_id: str, frame: int, destination: Path) -> dict:
        """Stream one JPEG to ``destination``, hashing as it goes.

        Returns transfer metadata (size, content-type, server + local SHA-256);
        the caller is responsible for asserting integrity and renaming into
        place (spec §15).
        """
        request = urllib.request.Request(
            f"{self.base_url}/projects/{project_id}/images/{frame}",
            headers=self._headers(),
            method="GET",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        size = 0
        with self._open(request, self.download_timeout) as response:
            content_type = response.headers.get("Content-Type")
            server_sha = _server_sha(response.headers)
            declared = _int_or_none(response.headers.get("Content-Length"))
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    hasher.update(chunk)
                    size += len(chunk)
        return {
            "content_type": content_type,
            "size_bytes": size,
            "declared_size_bytes": declared,
            "server_sha256": server_sha,
            "local_sha256": hasher.hexdigest(),
        }

    def list_images(self, project_id: str) -> list[dict]:
        """All images across pages (spec §7, §20 existence check).

        Uses the API's real cursor pagination: ``after_frame`` query param,
        ``has_more`` / ``next_after_frame`` in the response (see api_v1.md).
        The server has no ``offset``/``total`` — assuming those infinite-loops.
        """
        images: list[dict] = []
        after: int | None = None
        limit = 500
        while True:
            path = f"/projects/{project_id}/images?limit={limit}"
            if after is not None:
                path += f"&after_frame={after}"
            page = self._get_json(path)
            batch = page.get("images", [])
            images.extend(batch)
            if not batch or not page.get("has_more"):
                break
            next_after = page.get("next_after_frame")
            if next_after is None or next_after == after:
                break  # defensive: no cursor progress -> stop
            after = next_after
        return images

    def get_manifest(self, project_id: str) -> dict:
        return self._get_json(f"/projects/{project_id}/manifest")

    def delete_project(self, project_id: str) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/projects/{project_id}",
            headers=self._headers(extra={"X-Confirm-Delete": project_id}),
            method="DELETE",
        )
        with self._open(request, self.connect_timeout):
            return None


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _server_sha(headers) -> str | None:
    sha = headers.get("X-ScannerCam-SHA256")
    if sha:
        return sha.strip().strip('"').lower()
    etag = headers.get("ETag")
    if etag:
        return etag.strip().strip('"').lower()
    return None

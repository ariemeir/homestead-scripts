# ScannerCam iPhone App — MVP Technical Specification

Version 0.2 (revised after technical review — see "Revision notes" at the end).

## 0. Deployment environment

Concrete parameters for this build, as opposed to the general design below.

```text
Bundle identifier:   com.ariemeir.ScannerCam
Signing team ID:     C37565DT8L
Minimum iOS target:  iOS 17
Xcode:               26.2
Swift:               6.2.3
Third-party deps:    none

Paired device:       Arie's iPhone
Hardware:            iPhone 12 (iPhone13,2)
Device ID:           6F054B0F-6A0A-548E-9ED4-0C899AE07F65
Device codename:     saru

Controller codename: shika (pulls images; owns capture/turntable orchestration)
API port:            8765
Networks:            Wi-Fi (LAN, primary) and Tailscale (remote/fallback)
Tailscale hostname:  saru
Tailscale IP:        100.93.178.102
```

Because the app must also be reachable over Tailscale, the server should bind
`0.0.0.0` (all interfaces) rather than only the Wi-Fi interface — Tailscale
presents as its own interface (`utun*`) with the `100.93.178.102` address.
Bonjour advertisement remains LAN-only by nature; when `shika` is off the home
network it should address the phone directly by Tailscale IP/hostname rather
than relying on discovery.

## 1. Purpose

ScannerCam turns an iPhone 12 into a remotely controlled still-image camera for a tabletop photogrammetry scanner.

The app must:

* Capture one high-quality JPEG on command.
* Store images locally, grouped by project.
* Use deterministic file names.
* Expose a local HTTP API over Wi-Fi (and Tailscale — see §0).
* Allow the controller (`shika`) to list and download images.
* Allow deletion of one project or all local scan data.
* Keep camera configuration stable throughout a project.
* Provide a minimal on-device preview and status interface.
* Require no cloud service, account, iCloud synchronization, or app-guided transfer process.

`shika` (the controller) is responsible for:

* Deciding when to capture.
* Deciding which project and frame number to use.
* Controlling or simulating turntable movement.
* Pulling images from the iPhone.
* Verifying downloads.
* Deleting iPhone-side files after successful transfer.

`saru` (the iPhone) is responsible for:

* Camera operation.
* Local image persistence.
* Serving its stored files.
* Reporting camera and storage state.

Apple's supported still-photo capture path is an `AVCaptureSession` with `AVCapturePhotoOutput`; each capture uses a fresh `AVCapturePhotoSettings` instance and receives the completed image through the capture delegate.

---

# 2. Scope

## 2.1 MVP scope

The MVP supports:

* One rear camera: iPhone 12 main wide camera, nominally 1×.
* JPEG output.
* Full available 4:3 still-photo resolution.
* Landscape or portrait orientation selected before capture.
* Local HTTP API.
* One active capture request at a time.
* Multiple named projects.
* Deterministic frame numbering.
* Listing projects.
* Listing project images.
* Downloading individual JPEGs.
* Downloading a project manifest.
* Deleting one project.
* Deleting all projects.
* Basic health and camera-status endpoints.
* Optional API-token authentication.
* Bonjour advertisement for discovery.
* Manual focus/exposure locking from the UI.
* Automatic creation of a project on first capture.

## 2.2 Explicitly out of scope for MVP

* Video recording.
* RAW or ProRAW.
* HEIC output.
* Burst capture.
* Multi-camera capture.
* Background capture while the app is suspended.
* Internet access.
* Remote access outside the local network / Tailscale.
* Automatic upload to the Mac.
* Bluetooth control.
* Arduino communication from the iPhone.
* Reconstruction.
* On-device image processing.
* Automated object masking.
* App Store distribution.

---

# 3. Intended Operating Model

The app must be open and active on the iPhone during a scan.

Typical sequence:

1. Launch ScannerCam.
2. Grant camera and local-network permissions.
3. Connect iPhone and controller to the same Wi-Fi network (or Tailscale).
4. Position and configure the camera.
5. Lock focus, exposure, and white balance.
6. Start the local API server.
7. `shika` checks `/api/v1/health`.
8. `shika` sends a capture request for project `red_mug`, frame `000000`.
9. ScannerCam captures and stores the JPEG.
10. `shika` requests frame `000000`.
11. `shika` performs the placeholder or Arduino turntable movement.
12. Repeat.
13. `shika` lists the project and verifies all expected frames.
14. `shika` downloads remaining images.
15. `shika` optionally deletes the project from ScannerCam.

The app must not depend on sequential conversational state. Every request includes enough information to stand alone.

For example, this must work directly:

```http
GET /api/v1/projects/red_mug/images/34
```

There is no requirement to first "open" project `red_mug` in the API.

---

# 4. Project and File Model

## 4.1 Project identifier

Each scan belongs to a `project_id`.

Allowed characters:

```text
a-z
A-Z
0-9
-
_
```

Length:

```text
1–64 characters
```

Examples:

```text
red_mug
red-mug-v2
gearbox_20260714
scan_001
```

Invalid examples:

```text
red mug
../../Documents
red/mug
赤いマグ
```

Unicode display names can come later. The MVP identifier remains ASCII-safe to avoid path and scripting headaches.

The server must reject invalid project IDs with HTTP `400`.

## 4.2 Frame number

Each image has an integer `frame`.

Range:

```text
0–999999
```

Frame numbers are formatted as six decimal digits:

```text
000000
000001
000034
000071
```

Using six digits avoids renaming if a future scan exceeds 9,999 captures.

## 4.3 Angle

Each capture request may include:

```json
"angle_degrees": 170.0
```

This value is metadata only. ScannerCam does not move the turntable and does not infer position.

Valid range:

```text
0.0 <= angle_degrees < 360.0
```

It may be omitted or set to `null`.

## 4.4 File naming format

**Revision note:** the original draft encoded angle into the filename
(`frame_<frame>_angle_<angle>.jpg`). Angle is informational and mutable
(overwrite can change it), while frame is the canonical, immutable identity —
encoding a mutable value into a supposedly-stable filename created an
overwrite bug (see §5.4). The filename is now frame-only; angle lives only in
the manifest and in the `Content-Disposition` header on download.

JPEG filename on disk:

```text
frame_<frame:06d>.jpg
```

Examples:

```text
frame_000000.jpg
frame_000001.jpg
frame_000034.jpg
```

This filename is an internal storage detail. Clients never need to construct
or parse it — they address images by `project_id` + `frame` through the API
(§8.8). For a human-friendly name on download, the server sets
`Content-Disposition` with a synthesized name that includes angle when known:

```text
frame_000034_angle_170.000.jpg
frame_000034_angle_unknown.jpg
```

## 4.5 Local directory structure

ScannerCam stores long-lived user-managed capture files beneath its app Documents directory. Apple documents the Documents directory as suitable for files managed by the user, within the app sandbox.

Logical structure:

```text
Documents/
└── ScannerCam/
    ├── app_state.json
    └── projects/
        └── red_mug/
            ├── project.json
            ├── manifest.json
            └── images/
                ├── frame_000000.jpg
                ├── frame_000001.jpg
                └── frame_000002.jpg
```

All file operations use Foundation `FileManager`, which supports creating, listing, moving, copying, and deleting files and directories.

## 4.6 Project metadata

`project.json`:

```json
{
  "schema_version": 1,
  "project_id": "red_mug",
  "created_at": "2026-07-14T12:30:00.000+09:00",
  "updated_at": "2026-07-14T12:42:12.000+09:00",
  "device": {
    "model": "iPhone 12",
    "system_version": "17.0"
  },
  "camera": {
    "position": "back",
    "lens": "wide",
    "requested_zoom_factor": 1.0,
    "output_format": "jpeg",
    "orientation": "landscapeRight"
  }
}
```

## 4.7 Manifest

`manifest.json` is rewritten atomically after every successful capture.

Example:

```json
{
  "schema_version": 1,
  "project_id": "red_mug",
  "image_count": 2,
  "images": [
    {
      "frame": 0,
      "angle_degrees": 0.0,
      "filename": "frame_000000.jpg",
      "captured_at": "2026-07-14T12:30:05.231+09:00",
      "size_bytes": 2840291,
      "width": 4032,
      "height": 3024,
      "sha256": "..."
    },
    {
      "frame": 1,
      "angle_degrees": 5.0,
      "filename": "frame_000001.jpg",
      "captured_at": "2026-07-14T12:30:11.918+09:00",
      "size_bytes": 2815577,
      "width": 4032,
      "height": 3024,
      "sha256": "..."
    }
  ]
}
```

The manifest order is ascending by frame number.

**Scaling note:** the manifest is fully rewritten on every capture. This is
fine at MVP scale (tens to low hundreds of frames per project) but becomes a
real per-capture cost for very large projects. The six-digit frame budget
(up to 999,999) is future headroom, not an MVP target — if projects routinely
grow past a few hundred frames, revisit this (e.g. an append-only log plus a
periodically-compacted manifest) rather than assuming the full-rewrite
approach scales indefinitely.

---

# 5. Capture Behavior

## 5.1 Camera selection

Default device:

```text
Back-facing wide-angle camera
```

Do not use:

* Front camera.
* Ultra-wide camera.
* Digital zoom.
* Portrait mode.
* Live Photos.
* Flash.
* Automatic lens switching.

The app should verify the selected physical device and expose its identity through the status API.

## 5.2 Output format

MVP output:

```text
JPEG
```

Requirements:

* Highest practical still-image dimensions supported by the active camera configuration.
* 4:3 aspect ratio.
* Quality-prioritized capture.
* No thumbnail-only output.
* No recompression after AVFoundation produces the JPEG.
* Preserve embedded EXIF metadata where available.

AVFoundation supports explicit capture quality prioritization on photo output.

## 5.3 Capture lifecycle

A capture request proceeds as follows:

1. Validate request.
2. Validate camera state.
3. Reject if another capture is active.
4. Resolve project directory.
5. Check whether target frame already exists (`frame_<frame:06d>.jpg` — a
   direct existence check, since filename no longer depends on angle).
6. Create a new `AVCapturePhotoSettings`.
7. Initiate capture.
8. Receive processed photo data.
9. Validate non-empty JPEG data.
10. Write to a temporary file.
11. Compute SHA-256.
12. Atomically rename the temporary file to its final filename.
13. Update manifest atomically.
14. Return success response.

Temporary filename:

```text
.pending_<UUID>.jpg
```

A final image must never appear through the API until the complete file has been written successfully.

## 5.4 Existing frame behavior

Default behavior:

```text
reject duplicate frame
```

If `frame_000034.jpg` already exists, return:

```http
409 Conflict
```

The request may explicitly allow replacement:

```json
{
  "project_id": "red_mug",
  "frame": 34,
  "angle_degrees": 170.0,
  "overwrite": true
}
```

With overwrite enabled:

1. Capture new image to a temporary file.
2. Verify new image.
3. Atomically rename the temporary file over `frame_000034.jpg`.
4. Update the manifest (including the new `angle_degrees`, which may differ
   from the previous value — since the filename is frame-only, this is a
   plain overwrite with no orphaned file from the old angle).
5. Return `"overwritten": true`.

## 5.5 Capture serialization

Only one capture may run at a time.

A second capture request received during capture returns:

```http
409 Conflict
```

Error code:

```json
{
  "error": {
    "code": "capture_in_progress",
    "message": "Another capture is currently in progress."
  }
}
```

No queue is required in the MVP. `shika` owns retry behavior.

## 5.6 Focus and exposure

The app UI supports:

* Tap-to-focus on preview.
* Tap-and-hold or button to lock focus.
* Lock exposure.
* Lock white balance.
* Unlock all.
* Exposure compensation slider.
* Optional manual focus slider where supported.

API capture must not silently refocus before every image when focus lock is enabled.

Status reports (this exact shape is returned both embedded in `GET /status`
and would be used by any future focus API — see revision note in §8.2):

```json
{
  "focus": {
    "mode": "locked",
    "lens_position": 0.43,
    "adjusting": false
  },
  "exposure": {
    "mode": "locked",
    "duration_seconds": 0.008333,
    "iso": 80,
    "target_offset": 0.0,
    "adjusting": false
  },
  "white_balance": {
    "mode": "locked",
    "adjusting": false
  }
}
```

A capture request may require locks:

```json
{
  "require_locks": true
}
```

When required and the camera is not locked, return `409`.

## 5.7 Orientation

The user selects one fixed output orientation in the app:

```text
portrait
portraitUpsideDown
landscapeLeft
landscapeRight
```

The app must not let incidental device motion rotate individual JPEGs differently during one project.

The active orientation is included in project metadata and capture responses.

---

# 6. Network Model

## 6.1 Transport

The app runs a local HTTP server while in the foreground.

Default port:

```text
8765
```

Base URL examples:

```text
http://192.168.1.42:8765           # LAN
http://100.93.178.102:8765         # Tailscale (saru)
```

The server binds `0.0.0.0` so both the Wi-Fi and Tailscale (`utun*`)
interfaces are reachable (see §0).

The app also advertises via Bonjour on the LAN:

```text
Service type: _scannercam._tcp
Instance name: ScannerCam-saru
```

Bonjour provides zero-configuration service discovery on a local network; it
does not cover the Tailscale path, where `shika` addresses the phone directly
by hostname (`saru`) or IP (`100.93.178.102`).

The app uses Apple's Network framework for TCP networking. Apple describes Network framework as the platform API for direct access to protocols such as TCP and UDP.

**HTTP implementation scope (revision note):** the MVP HTTP server is a
deliberately minimal HTTP/1.1 implementation with no third-party
dependencies. To keep that tractable, it explicitly does **not** implement
persistent connections or chunked transfer encoding. Every response:

* Sets `Content-Length` accurately (no chunked encoding).
* Sets `Connection: close`.
* Closes the TCP connection after the response is fully written.

This is a deliberate MVP cut, not an oversight — most HTTP/1.1 clients
(including `curl`) default to keep-alive and will otherwise sit waiting for
more bytes after a response that doesn't explicitly close. `shika`'s HTTP
client should not assume connection reuse.

## 6.2 Local-network permission

The app must include:

```text
NSLocalNetworkUsageDescription
```

Suggested text:

```text
ScannerCam uses your local network so your Mac can trigger captures and download scan images.
```

Apps accessing the local network must provide this usage description, and iOS prompts the user the first time local-network access is attempted.

The app must also declare its Bonjour service type in `NSBonjourServices`.

## 6.3 Authentication

MVP should use a shared bearer token even on the home LAN.

The app generates a random token on first launch:

```text
32 random bytes, base64url encoded
```

Example:

```text
Nz9rp1MaJjX_yD0qDt1qa3GpQdk5d_hvF14VcHqk18M
```

The token is displayed in the Settings screen and stored in the Keychain.

Every API request except `/api/v1/health` requires:

```http
Authorization: Bearer <token>
```

Token comparison must be constant-time (do not use `==` on the raw strings)
to avoid a timing side-channel, even though the practical exposure on a
private LAN/Tailscale tailnet is low.

Unauthorized response:

```http
401 Unauthorized
```

The health endpoint may return only minimal, non-sensitive information without authentication.

## 6.4 HTTP versus HTTPS

For a private MVP reachable over LAN and Tailscale, plain HTTP is acceptable provided:

* The bearer token is treated as local-network/tailnet-only.
* The Wi-Fi network is trusted.
* The server binds only to local/tailnet interfaces (never a public one).
* The user understands this is not safe over public/untrusted Wi-Fi outside the tailnet.

Tailscale's own WireGuard-based encryption covers the tailnet path; plain
HTTP inside that tunnel is materially different from plain HTTP on an open
network. Plain LAN HTTP is still acceptable for MVP under the constraints
above.

Later versions may add TLS or direct device pairing.

App Transport Security primarily governs outbound URL-loading connections made by apps; ScannerCam is acting as the local server, so ATS does not apply here.

---

# 7. API Conventions

Base path:

```text
/api/v1
```

Content types:

```text
application/json
image/jpeg
```

All timestamps:

```text
ISO 8601 with timezone and fractional seconds
```

Example:

```text
2026-07-14T12:30:05.231+09:00
```

All JSON keys:

```text
snake_case
```

All errors use:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Human-readable explanation.",
    "details": {}
  }
}
```

Each response includes:

```http
X-ScannerCam-Version: 0.1.0
Connection: close
```

Each successful JPEG response includes:

```http
Content-Type: image/jpeg
Content-Length: ...
ETag: "<sha256>"
X-ScannerCam-SHA256: ...
X-ScannerCam-Project-ID: red_mug
X-ScannerCam-Frame: 34
Content-Disposition: attachment; filename="frame_000034_angle_170.000.jpg"
```

---

# 8. API Endpoints

## 8.1 Health

```http
GET /api/v1/health
```

Authentication:

```text
Not required
```

Response:

```json
{
  "status": "ok",
  "app": "ScannerCam",
  "version": "0.1.0",
  "api_version": 1,
  "server_time": "2026-07-14T12:30:05.231+09:00"
}
```

Possible status values:

```text
ok
degraded
```

This endpoint does not expose projects, filenames, token, or device identifiers.

---

## 8.2 Detailed status

```http
GET /api/v1/status
```

**Revision note:** the original draft showed an abbreviated `focus`/`exposure`/
`white_balance` block here that omitted fields (`lens_position`,
`duration_seconds`, `iso`, `target_offset`) present in the §5.6 example,
which left it ambiguous which shape this endpoint actually returns. It
returns the full §5.6 shape, embedded under `camera`.

Response:

```json
{
  "status": "ready",
  "capture_in_progress": false,
  "camera": {
    "authorized": true,
    "session_running": true,
    "position": "back",
    "device_type": "builtInWideAngleCamera",
    "zoom_factor": 1.0,
    "orientation": "landscapeRight",
    "photo_dimensions": {
      "width": 4032,
      "height": 3024
    },
    "focus": {
      "mode": "locked",
      "lens_position": 0.43,
      "adjusting": false
    },
    "exposure": {
      "mode": "locked",
      "duration_seconds": 0.008333,
      "iso": 80,
      "target_offset": 0.0,
      "adjusting": false
    },
    "white_balance": {
      "mode": "locked",
      "adjusting": false
    }
  },
  "storage": {
    "project_count": 2,
    "image_count": 108,
    "used_bytes": 318492829,
    "free_bytes": 47204823040
  },
  "network": {
    "port": 8765,
    "bonjour_name": "ScannerCam-saru",
    "tailscale_ip": "100.93.178.102"
  }
}
```

---

## 8.3 Capture JPEG

```http
POST /api/v1/captures
```

Request:

```json
{
  "project_id": "red_mug",
  "frame": 34,
  "angle_degrees": 170.0,
  "overwrite": false,
  "require_locks": true,
  "request_id": "7c794aba-e203-4607-a67a-bcc33cbef890"
}
```

Required:

```text
project_id
frame
```

Optional defaults:

```json
{
  "angle_degrees": null,
  "overwrite": false,
  "require_locks": false,
  "request_id": null
}
```

Success:

```http
201 Created
```

```json
{
  "status": "captured",
  "request_id": "7c794aba-e203-4607-a67a-bcc33cbef890",
  "project_id": "red_mug",
  "frame": 34,
  "angle_degrees": 170.0,
  "filename": "frame_000034.jpg",
  "captured_at": "2026-07-14T12:30:05.231+09:00",
  "width": 4032,
  "height": 3024,
  "size_bytes": 2831049,
  "sha256": "...",
  "overwritten": false,
  "download_url": "/api/v1/projects/red_mug/images/34"
}
```

The endpoint returns only after the JPEG and manifest are safely stored.

Typical errors:

```text
400 invalid_request
400 invalid_project_id
400 invalid_frame
400 invalid_angle
401 unauthorized
409 capture_in_progress
409 frame_exists
409 camera_not_locked
409 request_id_conflict
423 camera_unavailable
507 insufficient_storage
500 capture_failed
500 file_write_failed
```

---

## 8.4 List projects

```http
GET /api/v1/projects
```

Response:

```json
{
  "projects": [
    {
      "project_id": "red_mug",
      "created_at": "2026-07-14T12:30:00.000+09:00",
      "updated_at": "2026-07-14T12:42:12.000+09:00",
      "image_count": 72,
      "size_bytes": 211902348
    },
    {
      "project_id": "blue_figurine",
      "created_at": "2026-07-13T18:10:00.000+09:00",
      "updated_at": "2026-07-13T18:18:04.000+09:00",
      "image_count": 36,
      "size_bytes": 105443992
    }
  ]
}
```

Ordering:

```text
updated_at descending
```

---

## 8.5 Read project

```http
GET /api/v1/projects/{project_id}
```

Response:

```json
{
  "project_id": "red_mug",
  "created_at": "2026-07-14T12:30:00.000+09:00",
  "updated_at": "2026-07-14T12:42:12.000+09:00",
  "image_count": 72,
  "size_bytes": 211902348,
  "minimum_frame": 0,
  "maximum_frame": 71,
  "missing_frames": [],
  "manifest_url": "/api/v1/projects/red_mug/manifest",
  "images_url": "/api/v1/projects/red_mug/images"
}
```

`missing_frames` is calculated between minimum and maximum existing frame numbers.

---

## 8.6 Read project manifest

```http
GET /api/v1/projects/{project_id}/manifest
```

Returns the complete `manifest.json`.

---

## 8.7 List images in project

```http
GET /api/v1/projects/{project_id}/images
```

Optional query parameters:

```text
after_frame
limit
```

Example:

```http
GET /api/v1/projects/red_mug/images?after_frame=31&limit=20
```

Response:

```json
{
  "project_id": "red_mug",
  "images": [
    {
      "frame": 32,
      "angle_degrees": 160.0,
      "filename": "frame_000032.jpg",
      "captured_at": "2026-07-14T12:38:31.200+09:00",
      "width": 4032,
      "height": 3024,
      "size_bytes": 2829022,
      "sha256": "...",
      "download_url": "/api/v1/projects/red_mug/images/32"
    }
  ],
  "next_after_frame": 51,
  "has_more": true
}
```

Default:

```text
limit=100
```

Maximum:

```text
limit=500
```

Listing must not block on the capture lock for longer than a manifest-read
snapshot — it reads a copy of the in-memory manifest state rather than
serializing behind the capture's file-write critical section.

---

## 8.8 Download one JPEG

Canonical endpoint:

```http
GET /api/v1/projects/{project_id}/images/{frame}
```

Example:

```http
GET /api/v1/projects/red_mug/images/34
```

Response:

```http
200 OK
Content-Type: image/jpeg
Content-Disposition: attachment; filename="frame_000034_angle_170.000.jpg"
Content-Length: 2831049
ETag: "<sha256>"
X-ScannerCam-SHA256: <sha256>
```

Body:

```text
Raw JPEG bytes
```

The endpoint supports:

```http
HEAD /api/v1/projects/{project_id}/images/{frame}
```

This allows `shika` to inspect size and hash without downloading the image.

The endpoint should support HTTP byte ranges if the chosen server implementation makes that reasonable, but range support is not required for the first build.

**Concurrency note:** the download handler opens a file handle to the image
before streaming any bytes, and streams from that handle to completion. A
concurrent `DELETE` of the image or its project unlinks the directory entry
but does not invalidate an already-open handle (standard POSIX/APFS unlink
semantics), so an in-flight download completes correctly even if a delete
request lands mid-stream. New requests for a deleted image return `404` as
usual.

---

## 8.9 Delete one image

```http
DELETE /api/v1/projects/{project_id}/images/{frame}
```

Success:

```http
204 No Content
```

This endpoint is useful for recovering from a bad frame without deleting the project.

It updates the manifest atomically.

---

## 8.10 Delete project

```http
DELETE /api/v1/projects/{project_id}
```

To reduce accidental deletion, require:

```http
X-Confirm-Delete: <project_id>
```

Example:

```http
DELETE /api/v1/projects/red_mug
X-Confirm-Delete: red_mug
```

Success:

```http
204 No Content
```

The entire project directory is removed.

If the project is currently being written:

```http
409 Conflict
```

---

## 8.11 Delete all local scan data

```http
DELETE /api/v1/projects
```

Require:

```http
X-Confirm-Delete: DELETE_ALL_SCANNERCAM_PROJECTS
```

Response:

```json
{
  "status": "deleted",
  "deleted_projects": 4,
  "deleted_images": 216,
  "freed_bytes": 634022134
}
```

The app itself, settings, API token, and camera preferences remain intact.

This is equivalent to the on-device "Delete All Projects" action.

---

## 8.12 Storage summary

```http
GET /api/v1/storage
```

Response:

```json
{
  "project_count": 4,
  "image_count": 216,
  "scanner_data_bytes": 634022134,
  "device_free_bytes": 47204823040,
  "device_total_bytes": 128000000000
}
```

---

# 9. Idempotency and Retries

Capture requests support `request_id`.

ScannerCam retains a small request history in `app_state.json`.

If the same `request_id` is received again:

* If the original request succeeded, return the original successful capture metadata without taking another photo.
* If the original request is still running, return `409 capture_in_progress`.
* If the same `request_id` is reused with different capture parameters, return `409 request_id_conflict`.

This prevents network retry logic from accidentally creating two captures.

Retention:

```text
Most recent 1,000 request IDs
```

If a `request_id` has aged out of retention and is retried, the frame-exists
check in §5.4 still prevents an accidental duplicate capture as long as
`overwrite` is not set — retention eviction is a soft edge case, not a
correctness gap.

---

# 10. On-Device User Interface

## 10.1 Main camera screen

Elements:

```text
┌─────────────────────────────────┐
│ ScannerCam                READY │
├─────────────────────────────────┤
│                                 │
│         Camera preview          │
│                                 │
│                                 │
├─────────────────────────────────┤
│ Wide 1×          4032 × 3024    │
│ Focus: LOCKED                    │
│ Exposure: LOCKED                │
│ White balance: LOCKED           │
│                                 │
│ [Lock All] [Unlock]             │
│ [Test Capture]                  │
├─────────────────────────────────┤
│ API: Running                    │
│ 192.168.1.42:8765               │
│ ScannerCam-saru.local           │
│ Projects: 2   Images: 108       │
└─────────────────────────────────┘
```

Tapping the preview sets focus/exposure point before locking.

The app shows an obvious capture flash or status transition:

```text
READY → CAPTURING → SAVING → READY
```

## 10.2 Projects screen

Shows:

* Project ID.
* Image count.
* Storage consumed.
* Last capture time.
* Delete button.
* Inspect image list.

No rename operation in MVP.

## 10.3 Settings screen

Settings:

* API server enabled.
* Port.
* Bonjour device name.
* API token display/copy/regenerate.
* Image orientation.
* JPEG quality mode.
* Camera lens selection, fixed to supported devices.
* Show API examples.
* Delete all projects.
* Keep screen awake.
* Prevent device auto-lock while server is active.

## 10.4 Safety around deletion

Project deletion requires:

* Swipe action followed by confirmation, or
* Project detail → Delete → confirmation.

Delete-all requires entering:

```text
DELETE
```

or using a destructive confirmation sheet.

---

# 11. Application State and Lifecycle

## 11.1 Foreground requirement

The API server and camera capture are guaranteed only while ScannerCam is foreground-active.

When the app becomes inactive:

* Current file write is allowed to finish where possible.
* Server status transitions away from ready.
* New capture requests must not be accepted.
* The UI clearly shows that the Mac cannot reliably capture while the app is backgrounded.

**Operational note:** iOS suspends a foreground app within seconds of losing
active status — a phone call, Control Center swipe, notification banner
interaction, or app switch will drop the listener and any open connections.
This is a real, frequent interruption during a scan session, not a rare edge
case. Put the paired iPhone in Airplane Mode + Wi-Fi-on (or Do Not Disturb)
during a scan to suppress calls/notifications, and treat "app resumed
foreground after an interruption" as a normal recovery path `shika` should
handle (reconnect and re-check `/api/v1/health` before resuming captures),
not an exceptional failure.

## 11.2 Screen behavior

While the API server is enabled:

* Disable idle timer.
* Keep the preview active.
* Dim the preview optionally after inactivity, but do not suspend the capture session.
* Restore normal idle behavior when the server is disabled.

## 11.3 Startup recovery

On launch:

1. Scan for `.pending_*.jpg` files.
2. Remove incomplete pending files.
3. Verify each project manifest against actual JPEG files.
4. Rebuild manifest if missing or inconsistent.
5. Start camera.
6. Start API server if the saved setting says enabled.

---

# 12. Concurrency and Data Integrity

Use separate serialized execution contexts for:

* Camera session configuration.
* Capture execution.
* File-system mutation.
* HTTP request handling.

Rules:

* Camera session changes never occur concurrently with capture.
* Project deletion never occurs during a capture into that project.
* Manifest writes use temporary-file-plus-rename.
* JPEG writes use temporary-file-plus-rename.
* Read/download endpoints expose only finalized images.
* Downloads that are in flight when a delete request lands are unaffected
  (see §8.8 concurrency note) — an already-open file handle survives unlink.
* Listing endpoints read a manifest snapshot rather than blocking behind the
  capture critical section (see §8.7).

---

# 13. Logging

The app keeps a rolling local diagnostic log.

Example events:

```text
server_started
server_stopped
capture_requested
capture_started
capture_completed
capture_failed
image_downloaded
image_deleted
project_deleted
all_projects_deleted
manifest_rebuilt
camera_interrupted
storage_low
```

Each record:

```json
{
  "timestamp": "2026-07-14T12:30:05.231+09:00",
  "level": "info",
  "event": "capture_completed",
  "project_id": "red_mug",
  "frame": 34,
  "duration_ms": 612,
  "size_bytes": 2831049
}
```

Keep:

```text
Maximum 5 MB or 10 files
```

Add endpoint:

```http
GET /api/v1/logs/recent?limit=200
```

No remote deletion endpoint is necessary for logs.

---

# 14. Storage Protection

Before capture, require:

```text
At least 250 MB device free space
```

If below threshold:

```http
507 Insufficient Storage
```

The threshold should be configurable in code, not necessarily in the UI.

ScannerCam never automatically deletes projects.

The only automatic deletion permitted is cleanup of incomplete `.pending_` files.

---

# 15. API Examples

## Check health

```bash
curl \
  --fail \
  --silent \
  --show-error \
  http://saru.local:8765/api/v1/health
```

## Check detailed status

```bash
SCANNERCAM_TOKEN='replace-with-token'

curl \
  --fail \
  --silent \
  --show-error \
  -H "Authorization: Bearer ${SCANNERCAM_TOKEN}" \
  http://saru.local:8765/api/v1/status
```

## Capture frame 34

```bash
curl \
  --fail \
  --silent \
  --show-error \
  -X POST \
  -H "Authorization: Bearer ${SCANNERCAM_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "project_id": "red_mug",
    "frame": 34,
    "angle_degrees": 170.0,
    "overwrite": false,
    "require_locks": true,
    "request_id": "7c794aba-e203-4607-a67a-bcc33cbef890"
  }' \
  http://saru.local:8765/api/v1/captures
```

## Download JPEG 34

```bash
curl \
  --fail \
  --silent \
  --show-error \
  -H "Authorization: Bearer ${SCANNERCAM_TOKEN}" \
  --output frame_000034_angle_170.000.jpg \
  http://saru.local:8765/api/v1/projects/red_mug/images/34
```

## Verify remote file metadata

```bash
curl \
  --fail \
  --silent \
  --show-error \
  --head \
  -H "Authorization: Bearer ${SCANNERCAM_TOKEN}" \
  http://saru.local:8765/api/v1/projects/red_mug/images/34
```

## List project images

```bash
curl \
  --fail \
  --silent \
  --show-error \
  -H "Authorization: Bearer ${SCANNERCAM_TOKEN}" \
  http://saru.local:8765/api/v1/projects/red_mug/images
```

## Delete one project

```bash
curl \
  --fail \
  --silent \
  --show-error \
  -X DELETE \
  -H "Authorization: Bearer ${SCANNERCAM_TOKEN}" \
  -H 'X-Confirm-Delete: red_mug' \
  http://saru.local:8765/api/v1/projects/red_mug
```

## Delete all projects

```bash
curl \
  --fail \
  --silent \
  --show-error \
  -X DELETE \
  -H "Authorization: Bearer ${SCANNERCAM_TOKEN}" \
  -H 'X-Confirm-Delete: DELETE_ALL_SCANNERCAM_PROJECTS' \
  http://saru.local:8765/api/v1/projects
```

Over Tailscale, replace `saru.local` with `saru` or `100.93.178.102`.

---

# 16. Recommended Swift Architecture

```text
ScannerCam/
├── App/
│   ├── ScannerCamApp.swift
│   └── AppState.swift
├── Camera/
│   ├── CameraController.swift
│   ├── CameraConfiguration.swift
│   ├── PhotoCaptureProcessor.swift
│   └── CameraPreview.swift
├── Server/
│   ├── HTTPServer.swift
│   ├── HTTPRequest.swift
│   ├── HTTPResponse.swift
│   ├── Router.swift
│   ├── Authentication.swift
│   └── Routes/
│       ├── HealthRoutes.swift
│       ├── StatusRoutes.swift
│       ├── CaptureRoutes.swift
│       ├── ProjectRoutes.swift
│       └── StorageRoutes.swift
├── Storage/
│   ├── ProjectStore.swift
│   ├── ManifestStore.swift
│   ├── ImageStore.swift
│   ├── AppStateStore.swift
│   └── StorageModels.swift
├── Models/
│   ├── APIModels.swift
│   ├── CaptureModels.swift
│   └── ProjectModels.swift
├── Security/
│   └── KeychainTokenStore.swift
├── UI/
│   ├── CameraScreen.swift
│   ├── ProjectsScreen.swift
│   ├── ProjectDetailScreen.swift
│   └── SettingsScreen.swift
└── Utilities/
    ├── SHA256.swift
    ├── ISO8601.swift
    ├── AtomicFileWriter.swift
    └── Logger.swift
```

Recommended implementation choices:

* SwiftUI for UI.
* AVFoundation for camera.
* Network framework for the server socket.
* Foundation `FileManager` for storage.
* CryptoKit for SHA-256.
* Security framework/Keychain for bearer token.
* `NWListener` for accepting local TCP connections.
* A deliberately small HTTP/1.1 implementation sufficient for this API (see §6.1 scope note: no persistent connections, no chunked encoding).

No third-party dependencies are required for the MVP. (Project scaffolding
uses XcodeGen, a build-time tool that generates the `.xcodeproj` from
`project.yml` — it is not a Swift Package dependency embedded in the app.)

---

# 17. Acceptance Criteria

The MVP is complete when all of the following pass:

1. App launches on the physical iPhone 12.
2. Camera preview uses the rear wide camera.
3. User can lock focus and exposure.
4. `shika` can reach `/api/v1/health`.
5. Unauthorized capture requests fail.
6. Authorized capture creates one JPEG.
7. JPEG dimensions are reported correctly.
8. JPEG can be downloaded by project and frame number.
9. Downloaded SHA-256 equals server-reported SHA-256.
10. Capturing an existing frame without overwrite returns `409`.
11. Capture with overwrite replaces it, including when the new
    `angle_degrees` differs from the original — no orphaned file remains.
12. Listing projects returns accurate counts.
13. Listing images returns frames in ascending order.
14. Deleting one image updates the manifest.
15. Deleting one project removes all its files.
16. Delete-all removes every project but preserves settings and token.
17. Restarting the app preserves projects.
18. App recovers safely from an incomplete temporary file.
19. Thirty-six sequential captures complete without crash or frame mismatch.
20. Seventy-two sequential captures complete without crash or frame mismatch.
21. Backgrounding and re-foregrounding the app mid-project does not corrupt
    the manifest or leave a `.pending_*.jpg` file behind.
22. A download in flight completes successfully even if a delete request for
    the same image/project is issued concurrently (or, if the implementation
    chooses to reject concurrent deletes instead, that rejection is a clean
    error rather than a partial/corrupt response).
23. The app is reachable and functions correctly over Tailscale (not just LAN).

---

# 18. Post-MVP Extensions

Likely next additions:

* ZIP download of an entire project.
* Optional HEIC and RAW output.
* Remote focus/exposure configuration API.
* Live preview stream or low-resolution preview snapshots.
* Capture-session presets.
* Multi-ring metadata such as camera elevation.
* QR-based pairing.
* TLS.
* Automatic deletion after confirmed ingestion by `shika`.
* SFTP or direct push mode.
* Arduino status included in orchestration.
* Calibration target capture mode.
* Automatic sharpness scoring.
* Retake endpoint based on sharpness or exposure failure.
* HTTP keep-alive / persistent connections, if the minimal server's
  connection-per-request behavior becomes a real throughput bottleneck.

---

# 19. Revision notes (v0.1 → v0.2)

Applied after technical review of the original draft:

1. **Filename no longer encodes angle** (§4.4, §5.4). The original
   `frame_<frame>_angle_<angle>.jpg` naming broke on overwrite when the new
   capture had a different angle than the original — the old and new
   filenames wouldn't match, so "atomically replace" had no well-defined old
   file to replace, risking an orphaned JPEG per changed-angle overwrite.
   Filenames are now `frame_<frame:06d>.jpg`; angle is manifest-only and
   surfaces to clients only via `Content-Disposition` on download.
2. **HTTP server scope pinned down** (§6.1). "Deliberately small HTTP/1.1
   implementation" was underspecified in a way that risked real bugs (clients
   hanging on keep-alive). Now explicit: no persistent connections, no
   chunked encoding, `Connection: close` on every response.
3. **Delete-vs-download concurrency addressed** (§8.8, §12). Previously
   unspecified; now explicit that in-flight downloads survive a concurrent
   delete via POSIX unlink semantics, provided the implementation opens the
   file handle before streaming.
4. **`/status` schema disambiguated** (§8.2). The abbreviated example there
   previously conflicted with the fuller shape in §5.6; now a single shape is
   used in both places.
5. **Listing vs. capture blocking clarified** (§8.7, §12) as a manifest
   snapshot read rather than a vague "should not block longer than
   necessary."
6. **Constant-time token comparison** called out explicitly (§6.3).
7. **Manifest full-rewrite scaling caveat** added (§4.7) given the six-digit
   frame budget signals expectations beyond MVP-scale projects.
8. **Acceptance criteria expanded** (§17, items 21–23) to cover backgrounding
   mid-project, overwrite-with-changed-angle, delete/download race, and
   Tailscale reachability — none of which the original 20 criteria exercised.
9. **§0 added** with concrete deployment parameters (bundle ID, signing team,
   device IDs, Tailscale) supplied for this specific build.

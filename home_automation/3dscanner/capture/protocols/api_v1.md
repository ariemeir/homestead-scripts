# ScannerCam API v1 — protocol reference

Implementation-facing summary of the contract between `saru` (iPhone,
ScannerCam app, server) and `shika` (controller, client). Full rationale and
design discussion lives in [`docs/scannercam_spec.md`](../../docs/scannercam_spec.md) —
this file is the quick-reference contract both sides should code against.
Shared constants (port, regexes, limits) are in [`constants.json`](constants.json)
in this directory; load that file rather than re-hardcoding values in a
second place.

## Transport

- Base URL: `http://<host>:8765/api/v1` — `<host>` is `saru.local` (Bonjour,
  LAN only) or `saru` / `100.93.178.102` (Tailscale).
- No persistent connections: every response sends `Connection: close` and
  closes the socket. Do not assume the underlying TCP connection is reusable.
- No chunked transfer encoding: every response has an accurate
  `Content-Length`.
- Auth: `Authorization: Bearer <token>` on every endpoint except
  `GET /health`. Token is generated on-device and shown in Settings.
- All JSON keys are `snake_case`. All timestamps are ISO 8601 with timezone
  and fractional seconds.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | no | liveness check |
| GET | `/status` | yes | camera/storage/network state |
| POST | `/captures` | yes | trigger a capture |
| GET | `/projects` | yes | list projects |
| GET | `/projects/{project_id}` | yes | project summary + missing frames |
| GET | `/projects/{project_id}/manifest` | yes | full manifest.json |
| GET | `/projects/{project_id}/images` | yes | paginated image list |
| GET | `/projects/{project_id}/images/{frame}` | yes | download one JPEG |
| HEAD | `/projects/{project_id}/images/{frame}` | yes | size/hash without body |
| DELETE | `/projects/{project_id}/images/{frame}` | yes | delete one image |
| DELETE | `/projects/{project_id}` | yes | delete a project (needs `X-Confirm-Delete: <project_id>`) |
| DELETE | `/projects` | yes | delete everything (needs `X-Confirm-Delete: DELETE_ALL_SCANNERCAM_PROJECTS`) |
| GET | `/storage` | yes | device storage summary |
| GET | `/logs/recent?limit=200` | yes | recent diagnostic log entries |

## `POST /captures`

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

Only `project_id` and `frame` are required. `angle_degrees` may be `null`.

Success — `201 Created`:

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

`filename` is an internal storage detail (frame-only, no angle — see
revision note below). Always address images by `project_id` + `frame`, never
by constructing a filename client-side.

Errors: `400 invalid_request | invalid_project_id | invalid_frame |
invalid_angle`, `401 unauthorized`, `409 capture_in_progress | frame_exists |
camera_not_locked | request_id_conflict`, `423 camera_unavailable`,
`507 insufficient_storage`, `500 capture_failed | file_write_failed`.

## Idempotency

Pass a `request_id` (any client-generated string, UUID recommended) on
capture requests. Retrying the same `request_id`:

- returns the original success payload if it already succeeded (no second
  photo taken),
- returns `409 capture_in_progress` if still running,
- returns `409 request_id_conflict` if retried with *different* parameters.

The server retains the most recent 1,000 request IDs. `shika` should still
generate a fresh `request_id` per logical capture attempt rather than
relying on retention.

## Error envelope

All non-2xx JSON responses:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Human-readable explanation.",
    "details": {}
  }
}
```

## Download response headers

```http
200 OK
Content-Type: image/jpeg
Content-Disposition: attachment; filename="frame_000034_angle_170.000.jpg"
Content-Length: 2831049
ETag: "<sha256>"
X-ScannerCam-SHA256: <sha256>
Connection: close
```

Verify integrity by comparing the downloaded file's SHA-256 against
`X-ScannerCam-SHA256` (or use `HEAD` first to get it without transferring
the body).

## Revision note (v0.1 → v0.2)

The on-disk/URL filename used to encode angle
(`frame_000034_angle_170.000.jpg`) and was returned as `filename` in
capture/list responses. It's now frame-only (`frame_000034.jpg`) because an
`overwrite: true` capture with a *different* `angle_degrees` than the
original produced a different filename than the file it was supposed to
replace, orphaning the old file. Angle-bearing names now appear only in the
download `Content-Disposition` header, synthesized at response time, never
as the canonical on-disk name. If you previously hardcoded the
`frame_<n>_angle_<a>.jpg` pattern anywhere client-side, stop — use the
`download_url` / `filename` field from API responses instead.

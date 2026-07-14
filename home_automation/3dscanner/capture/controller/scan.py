#!/usr/bin/env python3
"""
Scan orchestration ("shika" side of the ScannerCam protocol).

Talks to the ScannerCam iPhone app ("saru") over the API described in
docs/scannercam_spec.md and capture/protocols/api_v1.md. Requires a bearer
token from ScannerCam's Settings screen, passed via --token or the
SCANNERCAM_TOKEN environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCAN_ROOT = PROJECT_ROOT / "scans" / "incoming"
DEFAULT_IPHONE_URL = "http://saru.local:8765"


def capture_photo(
    iphone_url: str,
    token: str,
    project_id: str,
    frame: int,
    angle_degrees: float,
    overwrite: bool = False,
    require_locks: bool = True,
    timeout_seconds: float = 30.0,
) -> dict:
    endpoint = f"{iphone_url.rstrip('/')}/api/v1/captures"

    payload = {
        "project_id": project_id,
        "frame": frame,
        "angle_degrees": angle_degrees,
        "overwrite": overwrite,
        "require_locks": require_locks,
        "request_id": str(uuid.uuid4()),
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail)["error"]["message"]
        except (json.JSONDecodeError, KeyError, TypeError):
            message = detail
        raise RuntimeError(
            f"ScannerCam rejected capture (HTTP {exc.code}): {message}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach ScannerCam at {endpoint}: {exc}"
        ) from exc


def check_health(iphone_url: str, timeout_seconds: float = 5.0) -> None:
    endpoint = f"{iphone_url.rstrip('/')}/api/v1/health"
    request = urllib.request.Request(endpoint, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach ScannerCam at {endpoint}: {exc}") from exc

    if body.get("status") not in ("ok", "degraded"):
        raise RuntimeError(f"ScannerCam health check returned unexpected body: {body}")


def move_turntable_noop(
    step_number: int,
    target_angle: float,
    interactive: bool,
) -> None:
    print()
    print(
        f"[MOVE placeholder] Rotate object to approximately "
        f"{target_angle:.1f}°."
    )

    if interactive:
        input("Press Enter when rotation is complete...")
    else:
        print(f"[MOVE placeholder] No-op for step {step_number}.")


def create_manifest(
    scan_directory: Path,
    project_id: str,
    degrees_per_photo: float,
    image_count: int,
) -> Path:
    scan_directory.mkdir(parents=True, exist_ok=False)
    (scan_directory / "images").mkdir()

    manifest = {
        "project_id": project_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "degrees_per_photo": degrees_per_photo,
        "expected_image_count": image_count,
        "images": [],
    }

    manifest_path = scan_directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    return manifest_path


def update_manifest(
    manifest_path: Path,
    frame: int,
    angle_degrees: float,
    capture_result: dict,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["images"].append(
        {
            "frame": frame,
            "angle_degrees": angle_degrees,
            "capture_result": capture_result,
        }
    )

    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture one iPhone still every N degrees via the ScannerCam API."
    )

    parser.add_argument(
        "--name",
        required=True,
        dest="project_id",
        help="Project ID, for example red_mug (ASCII letters/digits/-/_ only).",
    )

    parser.add_argument(
        "--degrees",
        type=float,
        default=10.0,
        help="Degrees between photos. Default: 10.",
    )

    parser.add_argument(
        "--iphone-url",
        default=os.environ.get("SCANNERCAM_URL", DEFAULT_IPHONE_URL),
        help=f"ScannerCam base URL. Default: {DEFAULT_IPHONE_URL} "
        "(or $SCANNERCAM_URL). Use the Tailscale address/hostname when off the LAN.",
    )

    parser.add_argument(
        "--token",
        default=os.environ.get("SCANNERCAM_TOKEN"),
        help="Bearer token from ScannerCam's Settings screen. "
        "Defaults to $SCANNERCAM_TOKEN. Required unless --dry-run.",
    )

    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=2.0,
        help="Wait after rotation before capture.",
    )

    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not pause for manual rotation.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow re-capturing a frame that already exists on the iPhone.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate capture without contacting the iPhone.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.degrees <= 0 or args.degrees > 360:
        print("--degrees must be greater than 0 and at most 360.")
        return 2

    image_count_float = 360.0 / args.degrees
    image_count = round(image_count_float)

    if abs(image_count - image_count_float) > 1e-9:
        print(
            "For the MVP, --degrees must divide evenly into 360.",
            file=sys.stderr,
        )
        return 2

    if not args.dry_run and not args.token:
        print(
            "A bearer token is required (--token or $SCANNERCAM_TOKEN). "
            "Find it in ScannerCam's Settings screen on saru, or use --dry-run.",
            file=sys.stderr,
        )
        return 2

    if not args.dry_run:
        try:
            check_health(args.iphone_url)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    scan_directory = DEFAULT_SCAN_ROOT / f"{timestamp}-{args.project_id}"

    manifest_path = create_manifest(
        scan_directory=scan_directory,
        project_id=args.project_id,
        degrees_per_photo=args.degrees,
        image_count=image_count,
    )

    print(f"Project:     {args.project_id}")
    print(f"Images:      {image_count}")
    print(f"Step:        {args.degrees:g}°")
    print(f"Destination: {scan_directory}")
    print()

    interactive = not args.non_interactive

    # Frames are 0-based, matching docs/scannercam_spec.md §4.2.
    for frame in range(image_count):
        angle_degrees = frame * args.degrees

        if frame > 0:
            move_turntable_noop(
                step_number=frame,
                target_angle=angle_degrees,
                interactive=interactive,
            )

            print(
                f"Waiting {args.settle_seconds:.1f}s "
                "for vibrations to settle..."
            )
            time.sleep(args.settle_seconds)

        print(
            f"Capturing frame {frame:06d} ({frame + 1}/{image_count}) "
            f"at {angle_degrees:.1f}°..."
        )

        if args.dry_run:
            capture_result = {
                "status": "dry-run",
                "filename": f"frame_{frame:06d}.jpg",
            }
        else:
            try:
                capture_result = capture_photo(
                    iphone_url=args.iphone_url,
                    token=args.token,
                    project_id=args.project_id,
                    frame=frame,
                    angle_degrees=angle_degrees,
                    overwrite=args.overwrite,
                )
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                print(f"Manifest retained at: {manifest_path}")
                return 1

        update_manifest(
            manifest_path=manifest_path,
            frame=frame,
            angle_degrees=angle_degrees,
            capture_result=capture_result,
        )

    print()
    print("Scan complete.")
    print(f"Manifest: {manifest_path}")
    print(
        f"Next: download images from {args.iphone_url}/api/v1/projects/"
        f"{args.project_id}/images (see capture/protocols/api_v1.md)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

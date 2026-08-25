from __future__ import annotations

import argparse
import mimetypes
import os
from contextlib import ExitStack
from pathlib import Path

import httpx


def optional_file(
    stack: ExitStack,
    path_value: str | None,
    field_name: str,
):
    if not path_value:
        return None
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{field_name} file was not found: {path}")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path.name, stack.enter_context(path.open("rb")), content_type


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a detected cattle anomaly to the COWOW API.",
    )
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--cattle-id")
    parser.add_argument("--status", required=True, choices=("warning", "danger"))
    parser.add_argument("--behavior", required=True)
    parser.add_argument("--confidence", type=float)
    parser.add_argument("--detected-at")
    parser.add_argument("--session-id")
    parser.add_argument("--image")
    parser.add_argument("--video")
    args = parser.parse_args()

    api_url = os.getenv(
        "COWOW_EVENT_API_URL",
        "https://hanwoo.koreacentral.cloudapp.azure.com/inference/events",
    )
    edge_id = os.getenv("COWOW_EDGE_ID", "EDGE-DEMO-01")
    edge_secret = os.getenv("COWOW_EDGE_SECRET", "")
    if not edge_secret:
        raise RuntimeError("COWOW_EDGE_SECRET is not configured.")

    data = {
        "cameraId": args.camera_id,
        "status": args.status,
        "behavior": args.behavior,
    }
    optional_values = {
        "cattleId": args.cattle_id,
        "confidence": args.confidence,
        "detectedAt": args.detected_at,
        "sessionId": args.session_id,
    }
    data.update({key: str(value) for key, value in optional_values.items() if value is not None})

    with ExitStack() as stack:
        files = {}
        image = optional_file(stack, args.image, "image")
        video = optional_file(stack, args.video, "video")
        if image:
            files["image"] = image
        if video:
            files["video"] = video

        response = httpx.post(
            api_url,
            headers={
                "X-Edge-Id": edge_id,
                "X-Edge-Secret": edge_secret,
            },
            data=data,
            files=files,
            timeout=300,
        )
        response.raise_for_status()
        print(response.json())


if __name__ == "__main__":
    main()

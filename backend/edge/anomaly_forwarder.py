from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import httpx
import numpy as np
from websockets.sync.client import connect


WS_URL = os.getenv("COWOW_INFERENCE_WS_URL", "ws://127.0.0.1:8100/ws/top")
EVENT_API_URL = os.getenv(
    "COWOW_EVENT_API_URL",
    "https://hanwoo.koreacentral.cloudapp.azure.com/inference/events",
)
EDGE_ID = os.getenv("COWOW_EDGE_ID", "").strip()
EDGE_SECRET = os.getenv("COWOW_EDGE_SECRET", "").strip()
CAMERA_ID = os.getenv("COWOW_CAMERA_ID", "CAMERA-01").strip()
CONFIDENCE = float(os.getenv("COWOW_ANOMALY_CONFIDENCE", "0.75"))
LYING_SECONDS = float(os.getenv("COWOW_LYING_WARNING_SECONDS", "300"))
COOLDOWN_SECONDS = float(os.getenv("COWOW_EVENT_COOLDOWN_SECONDS", "1800"))
CLIP_SECONDS = float(os.getenv("COWOW_EVENT_CLIP_SECONDS", "10"))
MAX_BUFFER_FRAMES = int(os.getenv("COWOW_MAX_BUFFER_FRAMES", "180"))


def validate_configuration() -> None:
    if not EDGE_ID or not EDGE_SECRET:
        raise RuntimeError("COWOW edge credentials are not configured")
    if LYING_SECONDS <= 0 or COOLDOWN_SECONDS <= 0 or CLIP_SECONDS <= 0:
        raise RuntimeError("anomaly timing configuration must be positive")


def decode_frame(encoded: str) -> tuple[bytes, np.ndarray]:
    jpeg = base64.b64decode(encoded, validate=True)
    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("inference frame is not a valid JPEG")
    return jpeg, frame


def write_clip(samples: list[tuple[float, bytes]], destination: Path) -> bool:
    frames: list[np.ndarray] = []
    for _, jpeg in samples:
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            frames.append(frame)
    if len(frames) < 2:
        return False

    height, width = frames[0].shape[:2]
    elapsed = max(samples[-1][0] - samples[0][0], 0.1)
    fps = min(15.0, max(1.0, (len(frames) - 1) / elapsed))
    writer = cv2.VideoWriter(
        str(destination),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        return False
    try:
        for frame in frames:
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height))
            writer.write(frame)
    finally:
        writer.release()
    return destination.is_file() and destination.stat().st_size > 0


def send_event(
    *,
    jpeg: bytes,
    samples: list[tuple[float, bytes]],
    confidence: float,
) -> str:
    detected_at = datetime.now(timezone.utc)
    session_id = "realtime-" + detected_at.strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    data = {
        "cameraId": CAMERA_ID,
        "status": "warning",
        "behavior": "long_lying",
        "confidence": str(round(confidence, 4)),
        "detectedAt": detected_at.isoformat(),
        "sessionId": session_id,
    }
    headers = {"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET}

    with tempfile.TemporaryDirectory(prefix="cowow-anomaly-") as temp_dir:
        clip_path = Path(temp_dir) / "evidence.mp4"
        files: dict[str, tuple[str, object, str]] = {
            "image": ("evidence.jpg", jpeg, "image/jpeg")
        }
        clip = None
        if write_clip(samples, clip_path):
            clip = clip_path.open("rb")
            files["video"] = ("evidence.mp4", clip, "video/mp4")
        try:
            response = httpx.post(
                EVENT_API_URL,
                headers=headers,
                data=data,
                files=files,
                timeout=300,
            )
            response.raise_for_status()
            return str(response.json()["eventId"])
        finally:
            if clip is not None:
                clip.close()


def run_forever() -> None:
    validate_configuration()
    frame_buffer: deque[tuple[float, bytes]] = deque(maxlen=MAX_BUFFER_FRAMES)
    lying_started_at: float | None = None
    last_event_at = 0.0

    while True:
        try:
            print(f"connecting inference stream: {WS_URL}", flush=True)
            with connect(WS_URL, open_timeout=20, close_timeout=5) as websocket:
                print("inference stream connected", flush=True)
                for raw_message in websocket:
                    payload = json.loads(raw_message)
                    if payload.get("type") != "result" or not payload.get("frame"):
                        continue
                    now = time.monotonic()
                    jpeg, _ = decode_frame(payload["frame"])
                    frame_buffer.append((now, jpeg))
                    while frame_buffer and now - frame_buffer[0][0] > CLIP_SECONDS:
                        frame_buffer.popleft()

                    lying_scores = [
                        float(item.get("behavior_confidence") or 0.0)
                        for item in payload.get("detections", [])
                        if item.get("behavior") == "lying"
                        and float(item.get("behavior_confidence") or 0.0) >= CONFIDENCE
                    ]
                    if not lying_scores:
                        lying_started_at = None
                        continue
                    if lying_started_at is None:
                        lying_started_at = now
                        continue
                    if now - lying_started_at < LYING_SECONDS:
                        continue
                    if now - last_event_at < COOLDOWN_SECONDS:
                        continue

                    event_id = send_event(
                        jpeg=jpeg,
                        samples=list(frame_buffer),
                        confidence=max(lying_scores),
                    )
                    last_event_at = now
                    print(f"anomaly event sent: {event_id}", flush=True)
        except Exception as exc:
            print(f"forwarder reconnect after error: {exc!r}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run_forever()



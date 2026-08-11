from __future__ import annotations

from pathlib import Path

import cv2


EVIDENCE_DIR = Path(__file__).resolve().parent / "feedback_evidence"


def capture_feedback_frame(
    input_path: str | None,
    frame_time_seconds: float,
    feedback_id: str,
) -> str | None:
    if not input_path:
        return None

    source = Path(input_path)
    if not source.exists():
        return None

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        return None

    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, frame_time_seconds) * 1000)
        success, frame = capture.read()
        if not success:
            return None

        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        evidence_path = EVIDENCE_DIR / f"{feedback_id}.jpg"
        if not cv2.imwrite(str(evidence_path), frame):
            return None
        return str(evidence_path)
    finally:
        capture.release()


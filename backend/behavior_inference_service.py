from __future__ import annotations

import argparse
import ast
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import cv2


BEHAVIOR_PACKAGE_DIR = Path(
    "/home/azureuser/models/detection/cow-model/"
    "hanwoo_behavior_anomaly_share_20260811"
)

DETECTOR_PATH = (
    BEHAVIOR_PACKAGE_DIR
    / "hanwoo_detector_v5_best.pt"
)

BEHAVIOR_MODEL_PATH = (
    BEHAVIOR_PACKAGE_DIR
    / "cow_behavior_v5_best.pt"
)

BEHAVIOR_SPECIALIST_PATH = (
    BEHAVIOR_PACKAGE_DIR
    / "cow_behavior_v6_specialist_best.pt"
)


def validate_behavior_models() -> None:
    required_files = [
        DETECTOR_PATH,
        BEHAVIOR_MODEL_PATH,
        BEHAVIOR_SPECIALIST_PATH,
        BEHAVIOR_PACKAGE_DIR / "cow_pipeline.py",
    ]

    missing = [
        path
        for path in required_files
        if not path.is_file()
    ]

    if missing:
        missing_text = "\n".join(
            str(path) for path in missing
        )
        raise FileNotFoundError(
            "행동 추론에 필요한 파일이 없습니다:\n"
            + missing_text
        )


def load_behavior_pipeline():
    validate_behavior_models()

    package_path = str(BEHAVIOR_PACKAGE_DIR)

    if package_path not in sys.path:
        sys.path.insert(0, package_path)

    import cow_pipeline

    return cow_pipeline


def read_video_metadata(
    video_path: Path,
) -> dict:
    capture = cv2.VideoCapture(str(video_path))

    if not capture.isOpened():
        raise RuntimeError(
            f"영상 정보를 읽을 수 없습니다: {video_path}"
        )

    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        width = int(
            capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        )
        height = int(
            capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )
        frame_count = int(
            capture.get(cv2.CAP_PROP_FRAME_COUNT)
        )
    finally:
        capture.release()

    duration = (
        frame_count / fps
        if fps > 0
        else None
    )

    return {
        "processed_frames": frame_count,
        "fps": fps,
        "width": width,
        "height": height,
        "duration_seconds": duration,
    }


def parse_behavior_counts(
    log_text: str,
) -> dict[str, int]:
    prefix = "Behavior labels:"

    for line in log_text.splitlines():
        if line.startswith(prefix):
            raw_value = line[len(prefix):].strip()

            try:
                parsed = ast.literal_eval(
                    raw_value
                )
            except (
                SyntaxError,
                ValueError,
            ):
                return {}

            if isinstance(parsed, dict):
                return {
                    str(key): int(value)
                    for key, value
                    in parsed.items()
                }

    return {}


def run_behavior_inference(
    input_path: Path,
    output_path: Path,
) -> dict:
    cow_pipeline = load_behavior_pipeline()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args = argparse.Namespace(
        weights=str(DETECTOR_PATH),
        verifier_weights="",
        behavior_weights=str(
            BEHAVIOR_MODEL_PATH
        ),
        behavior_specialist_weights=str(
            BEHAVIOR_SPECIALIST_PATH
        ),
        source=str(input_path),
        output=str(output_path),

        verifier_imgsz=224,
        verifier_conf=0.80,

        feeding_threshold=0.85,
        walking_threshold=0.55,
        behavior_imgsz=224,

        tracker="bytetrack.yaml",
        conf=0.05,
        iou=0.45,
        imgsz=960,
        classes=[0],

        window_seconds=1.0,
        min_history=5,
        move_threshold=0.12,
        lying_ratio=1.75,
    )

    log_buffer = io.StringIO()

    with redirect_stdout(log_buffer):
        cow_pipeline.track(args)

    log_text = log_buffer.getvalue()

    print(log_text, end="")

    if not output_path.is_file():
        raise RuntimeError(
            "행동 분석 결과 영상이 생성되지 않았습니다."
        )

    metadata = read_video_metadata(
        output_path
    )

    behavior_counts = parse_behavior_counts(
        log_text
    )

    return {
        **metadata,
        "behavior_counts": behavior_counts,
        "model": "hanwoo_behavior_v5_v6",
        "detector": DETECTOR_PATH.name,
        "behavior_model": (
            BEHAVIOR_MODEL_PATH.name
        ),
        "behavior_specialist": (
            BEHAVIOR_SPECIALIST_PATH.name
        ),
        "tracking": "bytetrack",
    }

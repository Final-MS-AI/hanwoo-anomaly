from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

from inference_jobs import update_job
from blob_video_storage import upload_result_video


MODEL_PATH = Path(
    "/home/azureuser/models/detection/roboflow-best.pt"
)

_model: YOLO | None = None


def get_model() -> YOLO:
    global _model

    if _model is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"모델 파일이 없습니다: {MODEL_PATH}"
            )

        _model = YOLO(str(MODEL_PATH))

    return _model


def convert_to_browser_mp4(
    source_path: Path,
    output_path: Path,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(output_path),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "FFmpeg 변환 실패:\n"
            + completed.stderr[-3000:]
        )


def run_model(
    input_path: Path,
    output_path: Path,
    job_id: str,
) -> dict:
    model = get_model()

    capture = cv2.VideoCapture(str(input_path))

    if not capture.isOpened():
        raise RuntimeError(
            f"입력 영상을 열 수 없습니다: {input_path}"
        )

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(
        capture.get(cv2.CAP_PROP_FRAME_COUNT)
    )

    if not fps or fps <= 0:
        fps = 30.0

    if width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError(
            "영상 크기를 확인할 수 없습니다."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_output_path = output_path.with_name(
        f"{output_path.stem}_temp.mp4"
    )

    writer = cv2.VideoWriter(
        str(temp_output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        capture.release()
        raise RuntimeError(
            "임시 결과 영상 파일을 만들지 못했습니다."
        )

    device = 0 if torch.cuda.is_available() else "cpu"

    frame_index = 0
    total_detections = 0
    max_cattle_in_frame = 0

    update_job(
        job_id,
        status="detecting",
        progress=10,
        message="소 객체 탐지 중",
    )

    try:
        while True:
            success, frame = capture.read()

            if not success:
                break

            result = model.predict(
                source=frame,
                conf=0.25,
                imgsz=640,
                device=device,
                verbose=False,
            )[0]

            box_count = (
                len(result.boxes)
                if result.boxes is not None
                else 0
            )

            total_detections += box_count
            max_cattle_in_frame = max(
                max_cattle_in_frame,
                box_count,
            )

            rendered_frame = result.plot()
            writer.write(rendered_frame)

            frame_index += 1

            if total_frames > 0:
                progress = 10 + int(
                    frame_index / total_frames * 80
                )
                progress = min(progress, 90)

                if frame_index == 1 or frame_index % 10 == 0:
                    update_job(
                        job_id,
                        status="detecting",
                        progress=progress,
                        message=(
                            f"소 객체 탐지 중 "
                            f"({frame_index}/{total_frames})"
                        ),
                    )

    finally:
        capture.release()
        writer.release()

    if frame_index == 0:
        temp_output_path.unlink(
            missing_ok=True,
        )
        raise RuntimeError(
            "영상 프레임을 읽지 못했습니다."
        )

    update_job(
        job_id,
        status="analyzing",
        progress=92,
        message="브라우저용 결과 영상 변환 중",
    )

    try:
        convert_to_browser_mp4(
            temp_output_path,
            output_path,
        )
    finally:
        temp_output_path.unlink(
            missing_ok=True,
        )

    return {
        "processed_frames": frame_index,
        "total_detections": total_detections,
        "max_cattle_in_frame": max_cattle_in_frame,
        "fps": fps,
        "width": width,
        "height": height,
        "device": str(device),
        "video_codec": "h264",
    }


def process_video_job(
    job_id: str,
    input_path: str,
    output_path: str,
    result_url: str,
) -> None:
    try:
        update_job(
            job_id,
            status="processing",
            progress=5,
            message="모델 준비 중",
        )

        summary = run_model(
            Path(input_path),
            Path(output_path),
            job_id,
        )

        update_job(
            job_id,
            status="analyzing",
            progress=97,
            message="결과 영상을 Blob Storage에 저장 중",
        )

        blob_result_url = upload_result_video(
            Path(output_path),
            job_id,
        )

        update_job(
            job_id,
            status="completed",
            progress=100,
            message="분석 완료",
            result_url=blob_result_url,
            summary=summary,
        )

        # Blob 업로드 완료 후 VM의 결과 파일을 제거합니다.
        Path(output_path).unlink(missing_ok=True)

    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            progress=0,
            message="영상 분석 실패",
            error=str(exc),
        )

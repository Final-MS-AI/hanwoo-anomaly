from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

from inference_jobs import update_job
from blob_video_storage import upload_result_video


MODEL_DIR = Path("/home/azureuser/models/feeding/feeding_frontal_handoff_v7")
DETECTOR_PATH = MODEL_DIR / "hanwoo_detector_v7_frontal_best.pt"
SPECIALIST_PATH = MODEL_DIR / "feeding_only_specialist_v3_best.pt"
SPECIALIST_CONF_THRESH = 0.5

_detector: YOLO | None = None
_specialist: YOLO | None = None


def get_models() -> tuple[YOLO, YOLO]:
    global _detector, _specialist

    if _detector is None:
        if not DETECTOR_PATH.exists():
            raise FileNotFoundError(f"탐지 모델 파일이 없습니다: {DETECTOR_PATH}")
        _detector = YOLO(str(DETECTOR_PATH))

    if _specialist is None:
        if not SPECIALIST_PATH.exists():
            raise FileNotFoundError(f"분류 모델 파일이 없습니다: {SPECIALIST_PATH}")
        _specialist = YOLO(str(SPECIALIST_PATH))

    return _detector, _specialist


def convert_to_browser_mp4(source_path: Path, output_path: Path) -> None:
    command = [
        "ffmpeg", "-y", "-i", str(source_path),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError("FFmpeg 변환 실패:\n" + completed.stderr[-3000:])


def run_feeding_model(input_path: Path, output_path: Path, job_id: str) -> dict:
    detector, specialist = get_models()

    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"입력 영상을 열 수 없습니다: {input_path}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    if not fps or fps <= 0:
        fps = 30.0
    if width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("영상 크기를 확인할 수 없습니다.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_name(f"{output_path.stem}_temp.mp4")

    writer = cv2.VideoWriter(
        str(temp_output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError("임시 결과 영상 파일을 만들지 못했습니다.")

    device = 0 if torch.cuda.is_available() else "cpu"

    frame_index = 0
    total_boxes = 0
    feeding_hits = 0

    update_job(job_id, status="detecting", progress=10, message="소 탐지 및 급이 판정 중")

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break

            result = detector.predict(
                source=frame, conf=0.25, imgsz=960, device=device,
                classes=[0], verbose=False,
            )[0]

            if result.boxes is not None:
                for box in result.boxes.xyxy.cpu().numpy():
                    x1, y1, x2, y2 = map(int, box.tolist())
                    crop = frame[max(0, y1):y2, max(0, x1):x2]
                    if crop.size == 0:
                        continue

                    cls_result = specialist.predict(crop, imgsz=224, verbose=False)[0]
                    name_to_idx = {v: k for k, v in cls_result.names.items()}
                    feeding_conf = float(cls_result.probs.data[name_to_idx["feeding"]])
                    is_feeding = feeding_conf >= SPECIALIST_CONF_THRESH

                    total_boxes += 1
                    feeding_hits += int(is_feeding)

                    color = (0, 255, 0) if is_feeding else (0, 0, 255)
                    label = f"feeding {feeding_conf:.2f}" if is_feeding else f"not_feeding {feeding_conf:.2f}"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, label, (x1, max(y1 - 8, 15)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            writer.write(frame)
            frame_index += 1

            if total_frames > 0:
                progress = 10 + int(frame_index / total_frames * 80)
                progress = min(progress, 90)
                if frame_index == 1 or frame_index % 10 == 0:
                    update_job(
                        job_id, status="detecting", progress=progress,
                        message=f"급이 판정 중 ({frame_index}/{total_frames})",
                    )

    finally:
        capture.release()
        writer.release()

    if frame_index == 0:
        temp_output_path.unlink(missing_ok=True)
        raise RuntimeError("영상 프레임을 읽지 못했습니다.")

    update_job(job_id, status="analyzing", progress=92, message="브라우저용 결과 영상 변환 중")

    try:
        convert_to_browser_mp4(temp_output_path, output_path)
    finally:
        temp_output_path.unlink(missing_ok=True)

    return {
        "processed_frames": frame_index,
        "total_boxes": total_boxes,
        "feeding_hits": feeding_hits,
        "feeding_ratio": round(feeding_hits / total_boxes, 4) if total_boxes else 0,
        "fps": fps,
        "width": width,
        "height": height,
        "device": str(device),
        "video_codec": "h264",
    }


def process_feeding_video_job(
    job_id: str, input_path: str, output_path: str, result_url: str
) -> None:
    try:
        update_job(job_id, status="processing", progress=5, message="모델 준비 중")

        summary = run_feeding_model(Path(input_path), Path(output_path), job_id)

        update_job(job_id, status="analyzing", progress=97, message="결과 영상을 Blob Storage에 저장 중")

        blob_result_url = upload_result_video(Path(output_path), job_id)

        update_job(
            job_id, status="completed", progress=100, message="분석 완료",
            result_url=blob_result_url, summary=summary,
        )

        Path(output_path).unlink(missing_ok=True)

    except Exception as exc:
        update_job(job_id, status="failed", progress=0, message="영상 분석 실패", error=str(exc))

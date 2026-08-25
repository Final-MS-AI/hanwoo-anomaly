from __future__ import annotations

import subprocess
from pathlib import Path

from behavior_inference_service import (
    run_behavior_inference,
)
from blob_video_storage import upload_result_video
from inference_jobs import update_job


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
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_output_path = output_path.with_name(
        f"{output_path.stem}_behavior_temp.mp4"
    )

    update_job(
        job_id,
        status="detecting",
        progress=10,
        message=(
            "한우 개체 추적 및 행동 분석 중 "
            "(standing / walking / lying / feeding)"
        ),
    )

    try:
        summary = run_behavior_inference(
            input_path=input_path,
            output_path=temp_output_path,
        )

        if not temp_output_path.is_file():
            raise RuntimeError(
                "행동 분석 결과 영상이 생성되지 않았습니다."
            )

        update_job(
            job_id,
            status="analyzing",
            progress=92,
            message="브라우저용 결과 영상 변환 중",
        )

        convert_to_browser_mp4(
            temp_output_path,
            output_path,
        )

    finally:
        temp_output_path.unlink(
            missing_ok=True,
        )

    if not output_path.is_file():
        raise RuntimeError(
            "최종 H.264 결과 영상이 생성되지 않았습니다."
        )

    return {
        **summary,
        "video_codec": "h264",
        "inference_type": "behavior_tracking",
    }


def process_video_job(
    job_id: str,
    input_path: str,
    output_path: str,
    result_url: str,
) -> None:
    input_file = Path(input_path)
    output_file = Path(output_path)

    try:
        update_job(
            job_id,
            status="processing",
            progress=5,
            message="행동 분석 모델 준비 중",
        )

        summary = run_model(
            input_file,
            output_file,
            job_id,
        )

        update_job(
            job_id,
            status="analyzing",
            progress=97,
            message=(
                "행동 분석 결과 영상을 "
                "Blob Storage에 저장 중"
            ),
        )

        blob_result_url = upload_result_video(
            output_file,
            job_id,
        )

        update_job(
            job_id,
            status="completed",
            progress=100,
            message="행동 분석 완료",
            result_url=blob_result_url,
            summary=summary,
        )

        output_file.unlink(
            missing_ok=True,
        )

    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            progress=0,
            message="행동 영상 분석 실패",
            error=str(exc),
        )

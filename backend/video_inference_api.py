from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    UploadFile,
)

from inference_jobs import create_job, get_job
from inference_service import process_video_job


router = APIRouter(
    prefix="/inference",
    tags=["Video inference"],
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "inference_results"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "application/octet-stream",
}


@router.post("/jobs")
async def create_inference_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
):
    extension = Path(
        video.filename or "video.mp4"
    ).suffix.lower()

    if extension not in {".mp4", ".webm", ".mov"}:
        raise HTTPException(
            status_code=400,
            detail="MP4, WebM 또는 MOV 영상만 가능합니다.",
        )

    job_id = uuid.uuid4().hex

    input_path = UPLOAD_DIR / f"{job_id}{extension}"
    output_filename = f"{job_id}_result.mp4"
    output_path = RESULT_DIR / output_filename
    result_url = f"/inference/results/{output_filename}"

    try:
        with input_path.open("wb") as output_file:
            shutil.copyfileobj(
                video.file,
                output_file,
            )
    finally:
        await video.close()

    create_job(
        job_id=job_id,
        input_path=str(input_path),
    )

    background_tasks.add_task(
        process_video_job,
        job_id,
        str(input_path),
        str(output_path),
        result_url,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
    }


@router.get("/jobs/{job_id}")
def read_inference_job(job_id: str):
    job = get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="추론 작업을 찾을 수 없습니다.",
        )

    return job

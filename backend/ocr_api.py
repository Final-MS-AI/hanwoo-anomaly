from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from cattle_repository import get_cattle_by_ear_tag
from ear_tag_ocr_repository import save_ear_tag_ocr_result

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from inference_jobs import create_job, get_job
from ocr_inference_service import (
    process_ocr_image,
    process_ocr_job,
)


router = APIRouter(
    prefix="/ocr",
    tags=["Ear tag OCR"],
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "ocr_uploads"

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

ALLOWED_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mov",
}

ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "application/octet-stream",
}


@router.post("/jobs", status_code=202)
async def create_ocr_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    camera_id: str = Form("camera_b_01"),
):
    filename = video.filename or "video.mp4"
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="MP4, WebM 또는 MOV 영상만 업로드할 수 있습니다.",
        )

    if (
        video.content_type
        and video.content_type not in ALLOWED_CONTENT_TYPES
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "지원하지 않는 영상 형식입니다. "
                f"content_type={video.content_type}"
            ),
        )

    job_id = uuid.uuid4().hex
    input_path = UPLOAD_DIR / f"{job_id}{extension}"

    try:
        with input_path.open("wb") as output_file:
            shutil.copyfileobj(
                video.file,
                output_file,
            )
    except Exception as exc:
        input_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail=f"영상 저장에 실패했습니다: {exc}",
        ) from exc
    finally:
        await video.close()

    if input_path.stat().st_size == 0:
        input_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="업로드된 영상 파일이 비어 있습니다.",
        )

    create_job(
        job_id=job_id,
        input_path=str(input_path),
    )

    background_tasks.add_task(
        process_ocr_job,
        job_id,
        str(input_path),
        camera_id,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "message": "귀표 OCR 작업이 등록되었습니다.",
        "status_url": f"/ocr/jobs/{job_id}",
        "result_url": f"/ocr/jobs/{job_id}/result",
    }


@router.get("/jobs/{job_id}")
def read_ocr_job(job_id: str):
    job = get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="OCR 작업을 찾을 수 없습니다.",
        )

    return job


@router.get("/jobs/{job_id}/result")
def read_ocr_result(job_id: str):
    job = get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="OCR 작업을 찾을 수 없습니다.",
        )

    status = job.get("status")

    if status == "failed":
        raise HTTPException(
            status_code=500,
            detail={
                "message": job.get("message"),
                "error": job.get("error"),
            },
        )

    if status != "completed":
        raise HTTPException(
            status_code=202,
            detail={
                "message": "OCR 작업이 아직 완료되지 않았습니다.",
                "status": status,
                "progress": job.get("progress", 0),
            },
        )

    result = job.get("summary")

    if result is None:
        raise HTTPException(
            status_code=500,
            detail="완료된 OCR 결과가 없습니다.",
        )

    return result


# ---------------------------------------------------------
# 소 등록용 귀표 사진 OCR API
# ---------------------------------------------------------

IMAGE_UPLOAD_DIR = BASE_DIR / "ocr_image_uploads"

IMAGE_UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/octet-stream",
}


@router.post("/ear-tag")
async def recognize_ear_tag_image(
    ear_tag_image: UploadFile = File(...),
):
    filename = (
        ear_tag_image.filename
        or "ear-tag.jpg"
    )

    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "JPG, JPEG, PNG 또는 WebP "
                "사진만 업로드할 수 있습니다."
            ),
        )

    if (
        ear_tag_image.content_type
        and ear_tag_image.content_type
        not in ALLOWED_IMAGE_CONTENT_TYPES
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "지원하지 않는 이미지 형식입니다. "
                f"content_type={ear_tag_image.content_type}"
            ),
        )

    request_id = uuid.uuid4().hex
    input_path = (
        IMAGE_UPLOAD_DIR
        / f"{request_id}{extension}"
    )

    try:
        with input_path.open("wb") as output_file:
            shutil.copyfileobj(
                ear_tag_image.file,
                output_file,
            )
    except Exception as exc:
        input_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail=f"귀표 사진 저장에 실패했습니다: {exc}",
        ) from exc
    finally:
        await ear_tag_image.close()

    if (
        not input_path.exists()
        or input_path.stat().st_size == 0
    ):
        input_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=400,
            detail="업로드된 귀표 사진이 비어 있습니다.",
        )

    try:
        result = process_ocr_image(
            image_path=str(input_path),
            request_id=request_id,
        )

        ear_tag_number = result.get(
            "ear_tag_number"
        )

        cattle = None

        if ear_tag_number:
            cattle = get_cattle_by_ear_tag(
                str(ear_tag_number)
            )

        raw_result = result.get(
            "raw_result"
        ) or {}

        verification = result.get(
            "verification"
        )

        evidence_local_path = result.get(
            "evidence_local_path"
        )

        ocr_log = save_ear_tag_ocr_result(
            request_id=request_id,
            cattle_id=(
                cattle.get("id")
                if cattle
                else None
            ),
            detected_ear_tag_number=(
                str(ear_tag_number)
                if ear_tag_number
                else None
            ),
            confidence=float(
                result.get("confidence")
                or 0.0
            ),
            ocr_status=str(
                result.get("reason")
                or (
                    "success"
                    if result.get("success")
                    else "unconfirmed"
                )
            ),
            verification=verification,
            requires_human_confirmation=bool(
                result.get(
                    "requires_human_confirmation",
                    False,
                )
            ),
            vote_count=int(
                result.get("vote_count")
                or 0
            ),
            evidence_local_path=evidence_local_path,
            final_result_path=result.get(
                "final_result_path"
            ),
            raw_result=raw_result,
        )

        return {
            "success": result.get(
                "success",
                False,
            ),
            "ear_tag_number": result.get(
                "ear_tag_number"
            ),
            "confidence": result.get(
                "confidence",
                0.0,
            ),
            "request_id": request_id,
            "reason": result.get("reason"),
            "requires_human_confirmation": result.get(
                "requires_human_confirmation",
                False,
            ),
            "vote_count": result.get(
                "vote_count",
                0,
            ),
            "registered": cattle is not None,
            "cattle": cattle,
            "ocr_log_id": ocr_log["id"],
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"귀표 OCR에 실패했습니다: {exc}",
        ) from exc

    finally:
        # 귀표 검출 실패 분석을 위해 업로드 원본을 임시 보존합니다.
        pass

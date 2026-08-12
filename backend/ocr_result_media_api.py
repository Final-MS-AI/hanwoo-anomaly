from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ear_tag_ocr_query_repository import (
    get_ear_tag_ocr_result_by_id,
)


router = APIRouter(
    prefix="/ocr/results",
    tags=["Ear tag OCR media"],
)


BASE_DIR = Path(__file__).resolve().parent

OCR_RESULTS_ROOT = (
    BASE_DIR / "ocr_results"
).resolve()

ALLOWED_IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def get_ocr_record_or_404(
    ocr_log_id: int,
) -> dict[str, Any]:
    try:
        record = get_ear_tag_ocr_result_by_id(
            ocr_log_id
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail="올바르지 않은 OCR 로그 ID입니다.",
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="OCR 이력을 찾을 수 없습니다.",
        )

    return record


def validate_result_path(
    path_value: str | None,
    *,
    require_image: bool,
) -> Path:
    if not path_value:
        raise HTTPException(
            status_code=404,
            detail="파일 경로가 저장되어 있지 않습니다.",
        )

    path = Path(path_value).resolve()

    try:
        path.relative_to(OCR_RESULTS_ROOT)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail="허용되지 않은 파일 경로입니다.",
        ) from exc

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="파일을 찾을 수 없습니다.",
        )

    if (
        require_image
        and path.suffix.lower()
        not in ALLOWED_IMAGE_SUFFIXES
    ):
        raise HTTPException(
            status_code=415,
            detail="지원하지 않는 이미지 형식입니다.",
        )

    return path


def build_image_response(
    image_path: Path,
) -> FileResponse:
    media_type = (
        mimetypes.guess_type(
            image_path.name
        )[0]
        or "application/octet-stream"
    )

    return FileResponse(
        path=image_path,
        media_type=media_type,
        filename=image_path.name,
        content_disposition_type="inline",
    )


@router.get("/{ocr_log_id}/evidence")
def get_ocr_evidence_image(
    ocr_log_id: int,
) -> FileResponse:
    record = get_ocr_record_or_404(
        ocr_log_id
    )

    image_path = validate_result_path(
        record.get("evidence_local_path"),
        require_image=True,
    )

    return build_image_response(
        image_path
    )


@router.get("/{ocr_log_id}/annotated")
def get_ocr_annotated_image(
    ocr_log_id: int,
) -> FileResponse:
    record = get_ocr_record_or_404(
        ocr_log_id
    )

    final_result_path = validate_result_path(
        record.get("final_result_path"),
        require_image=False,
    )

    candidates = sorted(
        path
        for pattern in (
            "*_annotated.jpg",
            "*_annotated.jpeg",
            "*_annotated.png",
            "*_annotated.webp",
        )
        for path in final_result_path.parent.rglob(
            pattern
        )
        if path.is_file()
    )

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=(
                "YOLO Bounding Box 이미지를 "
                "찾을 수 없습니다."
            ),
        )

    image_path = validate_result_path(
        str(candidates[0]),
        require_image=True,
    )

    return build_image_response(
        image_path
    )

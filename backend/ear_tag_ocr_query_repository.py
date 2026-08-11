from __future__ import annotations

import os
from typing import Any

import psycopg


def get_ear_tag_ocr_result_by_id(
    ocr_log_id: int,
) -> dict[str, Any] | None:
    """
    OCR 이력 ID로 귀표 OCR 결과 한 건을 조회합니다.

    기존 저장 로직은 변경하지 않고,
    이미지 조회 API에서 사용할 경로 정보만 읽습니다.
    """
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다."
        )

    normalized_id = int(ocr_log_id)

    if normalized_id <= 0:
        raise ValueError(
            "ocr_log_id는 1 이상의 정수여야 합니다."
        )

    with psycopg.connect(
        database_url
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    request_id,
                    cattle_id,
                    detected_ear_tag_number,
                    confidence,
                    ocr_status,
                    verification,
                    requires_human_confirmation,
                    vote_count,
                    evidence_local_path,
                    final_result_path,
                    created_at
                FROM public.ear_tag_ocr_results
                WHERE id = %s
                """,
                (normalized_id,),
            )

            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "request_id": row[1],
        "cattle_id": row[2],
        "detected_ear_tag_number": row[3],
        "confidence": float(row[4] or 0.0),
        "ocr_status": row[5],
        "verification": row[6],
        "requires_human_confirmation": row[7],
        "vote_count": row[8],
        "evidence_local_path": row[9],
        "final_result_path": row[10],
        "created_at": (
            row[11].isoformat()
            if row[11] is not None
            else None
        ),
    }

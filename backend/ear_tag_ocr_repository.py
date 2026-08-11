from __future__ import annotations

import json
import os
from typing import Any

import psycopg


def save_ear_tag_ocr_result(
    *,
    request_id: str,
    cattle_id: int | None,
    detected_ear_tag_number: str | None,
    confidence: float,
    ocr_status: str,
    verification: str | None,
    requires_human_confirmation: bool,
    vote_count: int,
    evidence_local_path: str | None,
    final_result_path: str | None,
    raw_result: dict[str, Any] | None,
) -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다."
        )

    normalized_request_id = str(request_id).strip()

    if not normalized_request_id:
        raise ValueError("request_id가 없습니다.")

    normalized_number = None

    if detected_ear_tag_number is not None:
        normalized_number = str(
            detected_ear_tag_number
        ).strip()

        if (
            len(normalized_number) != 9
            or not normalized_number.isdigit()
        ):
            raise ValueError(
                "귀표번호는 숫자 9자리여야 합니다."
            )

    normalized_confidence = float(confidence)

    if not 0.0 <= normalized_confidence <= 1.0:
        raise ValueError(
            "confidence는 0.0에서 1.0 사이여야 합니다."
        )

    normalized_vote_count = int(vote_count)

    if normalized_vote_count < 0:
        raise ValueError(
            "vote_count는 0 이상이어야 합니다."
        )

    with psycopg.connect(
        database_url
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.ear_tag_ocr_results (
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
                    raw_result
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s::jsonb
                )
                ON CONFLICT (request_id)
                DO UPDATE SET
                    cattle_id = EXCLUDED.cattle_id,
                    detected_ear_tag_number =
                        EXCLUDED.detected_ear_tag_number,
                    confidence = EXCLUDED.confidence,
                    ocr_status = EXCLUDED.ocr_status,
                    verification = EXCLUDED.verification,
                    requires_human_confirmation =
                        EXCLUDED.requires_human_confirmation,
                    vote_count = EXCLUDED.vote_count,
                    evidence_local_path =
                        EXCLUDED.evidence_local_path,
                    final_result_path =
                        EXCLUDED.final_result_path,
                    raw_result = EXCLUDED.raw_result
                RETURNING
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
                """,
                (
                    normalized_request_id,
                    cattle_id,
                    normalized_number,
                    normalized_confidence,
                    str(ocr_status),
                    verification,
                    bool(requires_human_confirmation),
                    normalized_vote_count,
                    evidence_local_path,
                    final_result_path,
                    json.dumps(
                        raw_result,
                        ensure_ascii=False,
                    )
                    if raw_result is not None
                    else None,
                ),
            )

            row = cursor.fetchone()

        connection.commit()

    if row is None:
        raise RuntimeError(
            "OCR 이력 저장 결과를 반환받지 못했습니다."
        )

    return {
        "id": row[0],
        "request_id": row[1],
        "cattle_id": row[2],
        "detected_ear_tag_number": row[3],
        "confidence": row[4],
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

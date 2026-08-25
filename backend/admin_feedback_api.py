from __future__ import annotations

import os
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import BaseModel

from admin_auth import require_admin


router = APIRouter(
    prefix="/admin/feedback",
    tags=["Admin feedback"],
)


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL이 설정되지 않았습니다.")
    return value


class FeedbackReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    note: str | None = None


@router.get("")
def list_feedback(
    status: Literal[
        "pending", "approved", "rejected", "exported"
    ] = Query("pending"),
    limit: int = Query(50, ge=1, le=200),
    admin=Depends(require_admin),
):
    with psycopg.connect(
        _database_url(),
        row_factory=dict_row,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id,
                       user_id,
                       job_id,
                       feedback_type,
                       predicted_label,
                       corrected_label,
                       comment,
                       review_status,
                       reviewer_note,
                       triage_stage,
                       anomaly_event_id,
                       event_source,
                       device_id,
                       evidence_blob_name,
                       video_blob_name,
                       created_at,
                       reviewed_at
                FROM model_feedback
                WHERE review_status = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (status, limit),
            )
            rows = [dict(row) for row in cursor.fetchall()]

    return {
        "status": status,
        "count": len(rows),
        "feedback": rows,
    }


@router.post("/{feedback_id}/review")
def review_feedback(
    feedback_id: str,
    body: FeedbackReviewRequest,
    admin=Depends(require_admin),
):
    with psycopg.connect(
        _database_url(),
        row_factory=dict_row,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE model_feedback
                SET review_status = %s,
                    reviewer_note = %s,
                    reviewed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                  AND review_status = 'pending'
                RETURNING id,
                          user_id,
                          job_id,
                          feedback_type,
                          predicted_label,
                          corrected_label,
                          review_status,
                          reviewer_note,
                          anomaly_event_id,
                          device_id,
                          reviewed_at
                """,
                (body.status, body.note, feedback_id),
            )
            row = cursor.fetchone()

        if row is None:
            connection.rollback()
            raise HTTPException(
                status_code=404,
                detail="검토 가능한 pending 피드백을 찾을 수 없습니다.",
            )

        connection.commit()

    return dict(row)

from __future__ import annotations

import json
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")
    return database_url


def create_feedback(record: dict[str, Any]) -> dict[str, Any]:
    with psycopg.connect(_database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO model_feedback (
                    id,
                    user_id,
                    job_id,
                    feedback_type,
                    frame_time_seconds,
                    track_id,
                    predicted_label,
                    corrected_label,
                    comment,
                    source_video_url,
                    result_video_url,
                    evidence_path,
                    inference_summary
                )
                VALUES (
                    %(id)s,
                    %(user_id)s,
                    %(job_id)s,
                    %(feedback_type)s,
                    %(frame_time_seconds)s,
                    %(track_id)s,
                    %(predicted_label)s,
                    %(corrected_label)s,
                    %(comment)s,
                    %(source_video_url)s,
                    %(result_video_url)s,
                    %(evidence_path)s,
                    %(inference_summary)s::jsonb
                )
                RETURNING id, job_id, feedback_type, review_status,
                          frame_time_seconds, evidence_path, created_at
                """,
                {
                    **record,
                    "inference_summary": json.dumps(
                        record.get("inference_summary"),
                        ensure_ascii=False,
                    ),
                },
            )
            created = cursor.fetchone()
        connection.commit()

    return dict(created)


def list_user_feedback(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    with psycopg.connect(_database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, job_id, feedback_type, frame_time_seconds,
                       track_id, predicted_label, corrected_label, comment,
                       review_status, reviewer_note, created_at, reviewed_at
                FROM model_feedback
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]


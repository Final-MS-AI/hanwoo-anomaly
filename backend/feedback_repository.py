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
                    inference_summary,
                    anomaly_event_id,
                    event_source,
                    device_id,
                    triage_stage,
                    evidence_blob_name,
                    feedback_fingerprint
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
                    %(inference_summary)s::jsonb,
                    %(anomaly_event_id)s,
                    %(event_source)s,
                    %(device_id)s,
                    %(triage_stage)s,
                    %(evidence_blob_name)s,
                    %(feedback_fingerprint)s
                )
                RETURNING id, job_id, feedback_type, review_status,
                          frame_time_seconds, evidence_path, created_at,
                          triage_stage, anomaly_event_id
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
                       review_status, reviewer_note, created_at, reviewed_at,
                       triage_stage, anomaly_event_id, weekly_batch_id
                FROM model_feedback
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]


def resolve_feedback_context(
    user_id: int,
    anomaly_event_id: str | None,
) -> dict[str, Any] | None:
    if not anomaly_event_id:
        return None

    normalized = anomaly_event_id.strip()
    with psycopg.connect(_database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            if normalized.isdigit():
                cursor.execute(
                    """
                    SELECT ae.id::text AS anomaly_event_id,
                           'behavior_baseline' AS event_source,
                           NULL::text AS device_id,
                           ae.anomaly_type AS predicted_label,
                           ae.message AS event_message,
                           NULL::text AS evidence_blob_name,
                           NULL::text AS video_blob_name,
                           ae.detected_at
                    FROM anomaly_events ae
                    JOIN cattle c ON c.id = ae.cattle_id
                    WHERE ae.id = %s AND c.user_id = %s
                    LIMIT 1
                    """,
                    (int(normalized), user_id),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

            cursor.execute(
                """
                SELECT e.id::text AS anomaly_event_id,
                       'realtime_device' AS event_source,
                       e.device_id,
                       e.behavior AS predicted_label,
                       e.behavior AS event_message,
                       e.image_blob_name AS evidence_blob_name,
                       e.video_blob_name,
                       e.detected_at
                FROM device_anomaly_events e
                WHERE e.id::text = %s
                  AND (
                    EXISTS (
                        SELECT 1 FROM device_owners o
                        WHERE o.device_id=e.device_id AND o.user_id=%s
                    )
                    OR EXISTS (
                        SELECT 1 FROM device_members m
                        WHERE m.device_id=e.device_id AND m.user_id=%s
                    )
                  )
                LIMIT 1
                """,
                (normalized, user_id, user_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import psycopg


MODEL_VERSION = "behavior-baseline-v1"


def get_database_url() -> str:
    database_url = os.getenv(
        "DATABASE_URL"
    )

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 "
            "설정되지 않았습니다."
        )

    return database_url


def resolve_cattle_id(
    national_id: str,
) -> int:
    normalized_id = str(
        national_id
    ).strip()

    if not normalized_id:
        raise ValueError(
            "national_id가 없습니다."
        )

    with psycopg.connect(
        get_database_url()
    ) as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM public.cattle
                WHERE national_id = %s
                ORDER BY id
                """,
                (normalized_id,),
            )

            rows = cursor.fetchall()

    if not rows:
        raise LookupError(
            f"등록된 cattle을 찾지 못했습니다: "
            f"{normalized_id}"
        )

    if len(rows) != 1:
        raise RuntimeError(
            "national_id에 여러 cattle이 "
            "매칭되었습니다: "
            f"{normalized_id}"
        )

    return int(
        rows[0][0]
    )


def get_active_behavior_events(
    *,
    cattle_id: int,
) -> list[dict[str, Any]]:
    with psycopg.connect(
        get_database_url()
    ) as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    cattle_id,
                    anomaly_type,
                    severity,
                    score,
                    message,
                    detected_at,
                    resolved_at,
                    is_active,
                    model_version
                FROM public.anomaly_events
                WHERE cattle_id = %s
                  AND model_version = %s
                  AND is_active = true
                ORDER BY id
                """,
                (
                    cattle_id,
                    MODEL_VERSION,
                ),
            )

            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "cattle_id": row[1],
            "anomaly_type": row[2],
            "severity": row[3],
            "score": row[4],
            "message": row[5],
            "detected_at": (
                row[6].isoformat()
                if row[6] is not None
                else None
            ),
            "resolved_at": (
                row[7].isoformat()
                if row[7] is not None
                else None
            ),
            "is_active": row[8],
            "model_version": row[9],
        }
        for row in rows
    ]


def upsert_behavior_event(
    *,
    connection: psycopg.Connection,
    cattle_id: int,
    event: dict[str, Any],
    detected_at: datetime | None = None,
) -> int:
    if detected_at is None:
        detected_at = datetime.now(
            timezone.utc
        )

    anomaly_type = str(
        event["anomaly_type"]
    )

    severity = str(
        event["severity"]
    )

    score = event.get(
        "score"
    )

    message = str(
        event["message"]
    )

    with connection.cursor() as cursor:

        cursor.execute(
            """
            SELECT id
            FROM public.anomaly_events
            WHERE cattle_id = %s
              AND anomaly_type = %s
              AND model_version = %s
              AND is_active = true
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                cattle_id,
                anomaly_type,
                MODEL_VERSION,
            ),
        )

        existing = cursor.fetchone()

        if existing is None:
            cursor.execute(
                """
                INSERT INTO public.anomaly_events (
                    cattle_id,
                    anomaly_type,
                    severity,
                    score,
                    message,
                    detected_at,
                    is_active,
                    model_version
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, true, %s
                )
                RETURNING id
                """,
                (
                    cattle_id,
                    anomaly_type,
                    severity,
                    score,
                    message,
                    detected_at,
                    MODEL_VERSION,
                ),
            )

            return int(
                cursor.fetchone()[0]
            )

        event_id = int(
            existing[0]
        )

        cursor.execute(
            """
            UPDATE public.anomaly_events
            SET
                severity = %s,
                score = %s,
                message = %s,
                detected_at = %s,
                resolved_at = NULL,
                is_active = true
            WHERE id = %s
            """,
            (
                severity,
                score,
                message,
                detected_at,
                event_id,
            ),
        )

        return event_id


def resolve_missing_behavior_events(
    *,
    connection: psycopg.Connection,
    cattle_id: int,
    active_anomaly_types: set[str],
    resolved_at: datetime | None = None,
) -> list[int]:
    if resolved_at is None:
        resolved_at = datetime.now(
            timezone.utc
        )

    with connection.cursor() as cursor:

        cursor.execute(
            """
            SELECT
                id,
                anomaly_type
            FROM public.anomaly_events
            WHERE cattle_id = %s
              AND model_version = %s
              AND is_active = true
            """,
            (
                cattle_id,
                MODEL_VERSION,
            ),
        )

        rows = cursor.fetchall()

        resolved_ids = []

        for event_id, anomaly_type in rows:
            if (
                anomaly_type
                in active_anomaly_types
            ):
                continue

            cursor.execute(
                """
                UPDATE public.anomaly_events
                SET
                    is_active = false,
                    resolved_at = %s
                WHERE id = %s
                """,
                (
                    resolved_at,
                    event_id,
                ),
            )

            resolved_ids.append(
                int(event_id)
            )

    return resolved_ids

from __future__ import annotations

import os
from typing import Any

import psycopg


def get_cattle_by_ear_tag(
    ear_tag_number: str,
) -> dict[str, Any] | None:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다."
        )

    normalized_ear_tag = str(
        ear_tag_number
    ).strip()

    if (
        len(normalized_ear_tag) != 9
        or not normalized_ear_tag.isdigit()
    ):
        raise ValueError(
            "귀표번호는 숫자 9자리여야 합니다."
        )

    with psycopg.connect(
        database_url
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    national_id,
                    ear_tag_number,
                    barn_id,
                    status,
                    created_at,
                    user_id
                FROM public.cattle
                WHERE ear_tag_number = %s
                LIMIT 1
                """,
                (
                    normalized_ear_tag,
                ),
            )

            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "national_id": row[1],
        "ear_tag_number": row[2],
        "barn_id": row[3],
        "status": row[4],
        "created_at": (
            row[5].isoformat()
            if row[5] is not None
            else None
        ),
        "user_id": row[6],
    }

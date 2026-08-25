from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Any

import psycopg


ANALYSIS_BEHAVIORS = {
    "lying",
    "standing",
    "walking",
}

EXCLUDED_BEHAVIORS = {
    "feeding",
}


def aggregate_cattle_behavior(
    *,
    national_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
    include_test: bool = False,
) -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다."
        )

    normalized_id = str(
        national_id
    ).strip()

    if not normalized_id:
        raise ValueError(
            "national_id가 없습니다."
        )

    where = [
        "national_id = %s",
        "behavior IS NOT NULL",
    ]

    params: list[Any] = [
        normalized_id,
    ]

    if not include_test:
        where.append(
            "session_id NOT LIKE %s"
        )
        params.append("test_%")

    if start is not None:
        where.append("ts >= %s")
        params.append(start)

    if end is not None:
        where.append("ts <= %s")
        params.append(end)

    condition = " AND ".join(where)

    query = f"""
        SELECT
            ts,
            segment_id,
            track_id,
            session_id,
            behavior,
            behavior_conf
        FROM public.v_identified_track_observation
        WHERE {condition}
        ORDER BY
            segment_id,
            ts
    """

    with psycopg.connect(
        database_url
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                params,
            )

            rows = cursor.fetchall()

    behavior_seconds = {
        behavior: 0.0
        for behavior
        in sorted(ANALYSIS_BEHAVIORS)
    }

    excluded_seconds = {
        behavior: 0.0
        for behavior
        in sorted(EXCLUDED_BEHAVIORS)
    }

    segment_rows: dict[
        int,
        list[tuple],
    ] = defaultdict(list)

    for row in rows:
        segment_rows[int(row[1])].append(
            row
        )

    observations_used = 0

    for segment_id, observations in (
        segment_rows.items()
    ):
        observations.sort(
            key=lambda item: item[0]
        )

        for current, following in zip(
            observations,
            observations[1:],
        ):
            current_ts = current[0]
            next_ts = following[0]

            delta = (
                next_ts - current_ts
            ).total_seconds()

            if delta <= 0:
                continue

            # 비정상적으로 긴 gap을 행동 지속시간으로
            # 그대로 계산하지 않습니다.
            if delta > 5.0:
                continue

            behavior = str(
                current[4]
            ).lower()

            if behavior in ANALYSIS_BEHAVIORS:
                behavior_seconds[
                    behavior
                ] += delta

                observations_used += 1

            elif behavior in EXCLUDED_BEHAVIORS:
                excluded_seconds[
                    behavior
                ] += delta

    behavior_seconds = {
        key: round(value, 3)
        for key, value
        in behavior_seconds.items()
    }

    excluded_seconds = {
        key: round(value, 3)
        for key, value
        in excluded_seconds.items()
    }

    analyzable_seconds = round(
        sum(
            behavior_seconds.values()
        ),
        3,
    )

    return {
        "national_id": normalized_id,
        "segments": len(segment_rows),
        "observations": len(rows),
        "observations_used": (
            observations_used
        ),
        "behavior_seconds": (
            behavior_seconds
        ),
        "excluded_seconds": (
            excluded_seconds
        ),
        "analyzable_seconds": (
            analyzable_seconds
        ),
    }

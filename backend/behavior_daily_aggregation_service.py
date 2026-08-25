from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from behavior_aggregation_service import (
    aggregate_cattle_behavior,
)


FARM_TIMEZONE = ZoneInfo(
    "Asia/Seoul"
)

UTC = ZoneInfo(
    "UTC"
)


def aggregate_cattle_behavior_for_day(
    *,
    national_id: str,
    target_date: date,
    include_test: bool = False,
) -> dict[str, Any]:
    local_start = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        tzinfo=FARM_TIMEZONE,
    )

    local_end = (
        local_start
        + timedelta(days=1)
    )

    utc_start = local_start.astimezone(
        UTC
    )

    utc_end = local_end.astimezone(
        UTC
    )

    result = aggregate_cattle_behavior(
        national_id=national_id,
        start=utc_start,
        end=utc_end,
        include_test=include_test,
    )

    return {
        "national_id": national_id,
        "date": target_date.isoformat(),
        "timezone": "Asia/Seoul",
        "period_start": (
            local_start.isoformat()
        ),
        "period_end": (
            local_end.isoformat()
        ),
        **{
            key: value
            for key, value in result.items()
            if key != "national_id"
        },
    }

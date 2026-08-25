from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any

from behavior_anomaly_policy import (
    ANALYSIS_BEHAVIORS,
    MIN_ANALYZABLE_SECONDS,
    MIN_BASELINE_VALID_DAYS,
    PREFERRED_BASELINE_DAYS,
)
from behavior_daily_aggregation_service import (
    aggregate_cattle_behavior_for_day,
)


def _behavior_ratios(
    daily_result: dict[str, Any],
) -> dict[str, float]:
    analyzable_seconds = float(
        daily_result.get(
            "analyzable_seconds",
            0.0,
        )
        or 0.0
    )

    if analyzable_seconds <= 0:
        return {
            behavior: 0.0
            for behavior
            in ANALYSIS_BEHAVIORS
        }

    behavior_seconds = (
        daily_result.get(
            "behavior_seconds"
        )
        or {}
    )

    return {
        behavior: round(
            float(
                behavior_seconds.get(
                    behavior,
                    0.0,
                )
                or 0.0
            )
            / analyzable_seconds,
            6,
        )
        for behavior
        in ANALYSIS_BEHAVIORS
    }


def build_behavior_baseline(
    *,
    national_id: str,
    target_date: date,
    include_test: bool = False,
    lookback_days: int = PREFERRED_BASELINE_DAYS,
) -> dict[str, Any]:
    if lookback_days < 1:
        raise ValueError(
            "lookback_days는 1 이상이어야 합니다."
        )

    daily_results = []
    valid_days = []

    for offset in range(
        lookback_days,
        0,
        -1,
    ):
        day = (
            target_date
            - timedelta(days=offset)
        )

        result = (
            aggregate_cattle_behavior_for_day(
                national_id=national_id,
                target_date=day,
                include_test=include_test,
            )
        )

        result = {
            **result,
            "behavior_ratios": (
                _behavior_ratios(result)
            ),
        }

        daily_results.append(result)

        if (
            float(
                result[
                    "analyzable_seconds"
                ]
            )
            >= MIN_ANALYZABLE_SECONDS
        ):
            valid_days.append(result)

    if (
        len(valid_days)
        < MIN_BASELINE_VALID_DAYS
    ):
        return {
            "national_id": national_id,
            "target_date": (
                target_date.isoformat()
            ),
            "status": (
                "insufficient_baseline"
            ),
            "lookback_days": (
                lookback_days
            ),
            "valid_days": (
                len(valid_days)
            ),
            "required_valid_days": (
                MIN_BASELINE_VALID_DAYS
            ),
            "minimum_analyzable_seconds": (
                MIN_ANALYZABLE_SECONDS
            ),
            "baseline_behavior_seconds": (
                None
            ),
            "baseline_behavior_ratios": (
                None
            ),
            "baseline_analyzable_seconds": (
                None
            ),
            "daily_results": (
                daily_results
            ),
        }

    baseline_seconds = {}
    baseline_ratios = {}

    for behavior in ANALYSIS_BEHAVIORS:
        second_values = [
            float(
                item[
                    "behavior_seconds"
                ].get(
                    behavior,
                    0.0,
                )
            )
            for item in valid_days
        ]

        ratio_values = [
            float(
                item[
                    "behavior_ratios"
                ].get(
                    behavior,
                    0.0,
                )
            )
            for item in valid_days
        ]

        baseline_seconds[
            behavior
        ] = round(
            median(second_values),
            3,
        )

        baseline_ratios[
            behavior
        ] = round(
            median(ratio_values),
            6,
        )

    baseline_analyzable_seconds = round(
        median(
            float(
                item[
                    "analyzable_seconds"
                ]
            )
            for item in valid_days
        ),
        3,
    )

    return {
        "national_id": national_id,
        "target_date": (
            target_date.isoformat()
        ),
        "status": "ready",
        "lookback_days": (
            lookback_days
        ),
        "valid_days": (
            len(valid_days)
        ),
        "required_valid_days": (
            MIN_BASELINE_VALID_DAYS
        ),
        "minimum_analyzable_seconds": (
            MIN_ANALYZABLE_SECONDS
        ),
        "baseline_behavior_seconds": (
            baseline_seconds
        ),
        "baseline_behavior_ratios": (
            baseline_ratios
        ),
        "baseline_analyzable_seconds": (
            baseline_analyzable_seconds
        ),
        "daily_results": (
            daily_results
        ),
    }

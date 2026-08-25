from __future__ import annotations

from datetime import date
from typing import Any

from behavior_anomaly_policy import (
    ANALYSIS_BEHAVIORS,
    BEHAVIOR_THRESHOLDS,
    MIN_ANALYZABLE_SECONDS,
)
from behavior_baseline_service import (
    _behavior_ratios,
    build_behavior_baseline,
)
from behavior_daily_aggregation_service import (
    aggregate_cattle_behavior_for_day,
)


STATUS_PRIORITY = {
    "normal": 0,
    "caution": 1,
    "anomaly": 2,
}


def _classify_change(
    *,
    behavior: str,
    current_ratio: float,
    baseline_ratio: float,
) -> dict[str, Any]:
    rule = BEHAVIOR_THRESHOLDS[
        behavior
    ]

    if baseline_ratio <= 0:
        return {
            "status": "insufficient_baseline_behavior",
            "current_ratio": round(
                current_ratio,
                6,
            ),
            "baseline_ratio": round(
                baseline_ratio,
                6,
            ),
            "change_ratio": None,
            "direction": None,
        }

    change_ratio = (
        current_ratio
        - baseline_ratio
    ) / baseline_ratio

    absolute_change = abs(
        change_ratio
    )

    status = "normal"

    if rule.direction == "decrease":
        decrease_ratio = (
            -change_ratio
            if change_ratio < 0
            else 0.0
        )

        if (
            decrease_ratio
            >= rule.anomaly_ratio
        ):
            status = "anomaly"

        elif (
            decrease_ratio
            >= rule.caution_ratio
        ):
            status = "caution"

    elif rule.direction == "both":
        if (
            absolute_change
            >= rule.anomaly_ratio
        ):
            status = "anomaly"

        elif (
            absolute_change
            >= rule.caution_ratio
        ):
            status = "caution"

    direction = (
        "increase"
        if change_ratio > 0
        else "decrease"
        if change_ratio < 0
        else "stable"
    )

    return {
        "status": status,
        "current_ratio": round(
            current_ratio,
            6,
        ),
        "baseline_ratio": round(
            baseline_ratio,
            6,
        ),
        "change_ratio": round(
            change_ratio,
            6,
        ),
        "direction": direction,
    }


def evaluate_cattle_behavior_anomaly(
    *,
    national_id: str,
    target_date: date,
    include_test: bool = False,
) -> dict[str, Any]:
    today = (
        aggregate_cattle_behavior_for_day(
            national_id=national_id,
            target_date=target_date,
            include_test=include_test,
        )
    )

    today_ratios = _behavior_ratios(
        today
    )

    today = {
        **today,
        "behavior_ratios": (
            today_ratios
        ),
    }

    if (
        float(
            today[
                "analyzable_seconds"
            ]
        )
        < MIN_ANALYZABLE_SECONDS
    ):
        return {
            "national_id": national_id,
            "date": (
                target_date.isoformat()
            ),
            "overall_status": (
                "insufficient_data"
            ),
            "reason": (
                "오늘의 유효 행동 관측 시간이 "
                "최소 기준보다 부족합니다."
            ),
            "today": today,
            "baseline": None,
            "behaviors": None,
        }

    baseline = build_behavior_baseline(
        national_id=national_id,
        target_date=target_date,
        include_test=include_test,
    )

    if baseline["status"] != "ready":
        return {
            "national_id": national_id,
            "date": (
                target_date.isoformat()
            ),
            "overall_status": (
                "insufficient_baseline"
            ),
            "reason": (
                "최근 정상 행동 baseline을 "
                "만들 데이터가 부족합니다."
            ),
            "today": today,
            "baseline": baseline,
            "behaviors": None,
        }

    baseline_ratios = (
        baseline[
            "baseline_behavior_ratios"
        ]
        or {}
    )

    behavior_results = {}

    overall_status = "normal"

    for behavior in ANALYSIS_BEHAVIORS:
        result = _classify_change(
            behavior=behavior,
            current_ratio=float(
                today_ratios.get(
                    behavior,
                    0.0,
                )
            ),
            baseline_ratio=float(
                baseline_ratios.get(
                    behavior,
                    0.0,
                )
            ),
        )

        behavior_results[
            behavior
        ] = result

        status = result["status"]

        if (
            status
            in STATUS_PRIORITY
            and STATUS_PRIORITY[status]
            > STATUS_PRIORITY[
                overall_status
            ]
        ):
            overall_status = status

    return {
        "national_id": national_id,
        "date": (
            target_date.isoformat()
        ),
        "overall_status": (
            overall_status
        ),
        "reason": None,
        "today": today,
        "baseline": baseline,
        "behaviors": behavior_results,
    }

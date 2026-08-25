from __future__ import annotations

from typing import Any


MODEL_VERSION = (
    "behavior-baseline-v1"
)


def build_behavior_anomaly_events(
    anomaly_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    behavior_anomaly_service 결과를
    anomaly_events 저장 후보로 변환합니다.

    이 함수는 DB에 아무것도 저장하지 않습니다.
    """

    overall_status = (
        anomaly_result.get(
            "overall_status"
        )
    )

    if overall_status in {
        "insufficient_data",
        "insufficient_baseline",
    }:
        return []

    behavior_results = (
        anomaly_result.get(
            "behaviors"
        )
        or {}
    )

    events: list[
        dict[str, Any]
    ] = []

    for behavior, result in (
        behavior_results.items()
    ):
        status = result.get(
            "status"
        )

        if status not in {
            "caution",
            "anomaly",
        }:
            continue

        severity = (
            "warning"
            if status == "caution"
            else "danger"
        )

        change_ratio = result.get(
            "change_ratio"
        )

        direction = result.get(
            "direction"
        )

        score = (
            min(
                abs(float(change_ratio)),
                1.0,
            )
            if change_ratio is not None
            else None
        )

        if (
            behavior == "walking"
            and direction == "decrease"
        ):
            anomaly_type = (
                "movement_decrease"
            )
            message = (
                "평소 대비 보행 활동 비율이 "
                f"{abs(change_ratio) * 100:.1f}% "
                "감소했습니다."
            )

        elif (
            behavior == "lying"
            and direction == "increase"
        ):
            anomaly_type = (
                "long_lying"
            )
            message = (
                "평소 대비 누움 행동 비율이 "
                f"{abs(change_ratio) * 100:.1f}% "
                "증가했습니다."
            )

        elif behavior == "lying":
            anomaly_type = (
                "lying_decrease"
            )
            message = (
                "평소 대비 누움 행동 비율이 "
                f"{abs(change_ratio) * 100:.1f}% "
                "감소했습니다."
            )

        elif behavior == "standing":
            anomaly_type = (
                "standing_change"
            )
            korean_direction = (
                "증가"
                if direction == "increase"
                else "감소"
            )
            message = (
                "평소 대비 기립 행동 비율이 "
                f"{abs(change_ratio) * 100:.1f}% "
                f"{korean_direction}했습니다."
            )

        else:
            continue

        events.append(
            {
                "behavior": behavior,
                "anomaly_type": (
                    anomaly_type
                ),
                "severity": severity,
                "score": (
                    round(score, 6)
                    if score is not None
                    else None
                ),
                "message": message,
                "model_version": (
                    MODEL_VERSION
                ),
                "change_ratio": (
                    change_ratio
                ),
                "current_ratio": (
                    result.get(
                        "current_ratio"
                    )
                ),
                "baseline_ratio": (
                    result.get(
                        "baseline_ratio"
                    )
                ),
            }
        )

    return events

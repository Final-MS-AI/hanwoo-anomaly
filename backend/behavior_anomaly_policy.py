from __future__ import annotations

from dataclasses import dataclass

from feedback_policy_runtime import apply_policy_overrides


ANALYSIS_BEHAVIORS = (
    "lying",
    "standing",
    "walking",
)

EXCLUDED_BEHAVIORS = (
    "feeding",
)


@dataclass(frozen=True)
class BehaviorThreshold:
    caution_ratio: float
    anomaly_ratio: float
    direction: str


BEHAVIOR_THRESHOLDS = {
    "lying": BehaviorThreshold(
        caution_ratio=0.30,
        anomaly_ratio=0.50,
        direction="both",
    ),
    "walking": BehaviorThreshold(
        caution_ratio=0.30,
        anomaly_ratio=0.50,
        direction="decrease",
    ),
    "standing": BehaviorThreshold(
        caution_ratio=0.30,
        anomaly_ratio=0.50,
        direction="both",
    ),
}

BEHAVIOR_THRESHOLDS = apply_policy_overrides(BEHAVIOR_THRESHOLDS)


# 프로젝트 초기값.
# 수의학적 진단 기준이 아니라 데이터 품질 보호용 설정입니다.
MIN_BASELINE_VALID_DAYS = 3

PREFERRED_BASELINE_DAYS = 7

MIN_ANALYZABLE_SECONDS = 3600.0

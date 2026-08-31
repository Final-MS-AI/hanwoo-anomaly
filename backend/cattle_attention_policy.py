from __future__ import annotations

import os
from typing import Any

# COWOW 왼쪽 '주의' 선별 기준.
# - 급이대 체류비율: Belaid et al.에서 질병군의 약 18% 감소 관찰값을 참고한
#   프로젝트 운영용 주의 선별 기준. 질병 진단 cutoff가 아니다.
# - 누움비율: 개인 10일 평균 대비 30% 감소 alert rule을 참고한 주의 기준.
FEED_BUNK_WARNING_DECREASE_RATIO = 0.18
LYING_WARNING_DECREASE_RATIO = 0.30

BASELINE_REQUIRED_VALID_DAYS = 10

# 데이터 품질 gate. 수의학적 기준이 아니라 계산 신뢰성 보호용 엔지니어링 값이다.
# 기존 팀 behavior pipeline의 1시간 최소 관찰값을 기본값으로만 재사용하되,
# 환경변수로 변경 가능하게 둔다.
MIN_VALID_OBSERVATION_SEC = float(
    os.getenv("COWOW_ATTENTION_MIN_VALID_OBSERVATION_SEC", "3600")
)

# 프레임/관측 간격이 너무 길면 그 구간 전체를 행동 지속으로 간주하지 않는다.
MAX_OBSERVATION_GAP_SEC = float(
    os.getenv("COWOW_ATTENTION_MAX_OBSERVATION_GAP_SEC", "5")
)

# 10개 유효일을 찾기 위해 과거로 탐색하는 최대 달력일 수.
BASELINE_LOOKBACK_MAX_DAYS = int(
    os.getenv("COWOW_ATTENTION_BASELINE_LOOKBACK_MAX_DAYS", "60")
)

# 현재 track_zone의 기존 'top'은 역전파용 초크포인트일 수 있으므로 자동 재사용하지 않는다.
# 급이대 체류 분석용 ROI를 별도로 'feed_bunk' 이름으로 등록하는 것을 기본으로 한다.
# 현재 track_segment에는 device_id가 없으므로 개체 관측과 특정 장비 zone을 안전하게
# 결합할 근거가 없다. 따라서 이 분석은 camera A의 전역(device_id IS NULL) zone만 사용한다.
FEED_BUNK_ZONE_NAME = os.getenv("COWOW_FEED_BUNK_ZONE_NAME", "feed_bunk")
TRACK_CAMERA_ID = os.getenv("COWOW_ATTENTION_TRACK_CAMERA_ID", "A")
MODEL_VERSION = os.getenv("COWOW_ATTENTION_MODEL_VERSION", "cowow-attention-v1")


def classify_attention_changes(
    *,
    feed_bunk_change_ratio: float | None,
    lying_change_ratio: float | None,
) -> dict[str, Any]:
    """두 핵심 지표만 사용해 COWOW 왼쪽 '주의' 여부를 판정한다.

    walking/standing 변화는 화면 참고값으로 저장할 수 있지만 여기서는 사용하지 않는다.
    """

    warning_reasons: list[dict[str, Any]] = []

    if (
        feed_bunk_change_ratio is not None
        and feed_bunk_change_ratio <= -FEED_BUNK_WARNING_DECREASE_RATIO
    ):
        warning_reasons.append(
            {
                "metric": "feed_bunk",
                "label": "급이대 체류",
                "threshold": -FEED_BUNK_WARNING_DECREASE_RATIO,
                "change_ratio": feed_bunk_change_ratio,
            }
        )

    if (
        lying_change_ratio is not None
        and lying_change_ratio <= -LYING_WARNING_DECREASE_RATIO
    ):
        warning_reasons.append(
            {
                "metric": "lying",
                "label": "누움",
                "threshold": -LYING_WARNING_DECREASE_RATIO,
                "change_ratio": lying_change_ratio,
            }
        )

    primary = min(
        warning_reasons,
        key=lambda item: item["change_ratio"],
        default=None,
    )

    return {
        "status": "warning" if warning_reasons else "normal",
        "warning_reasons": warning_reasons,
        "primary_metric": primary["label"] if primary else "이상 징후 없음",
        "primary_change_ratio": primary["change_ratio"] if primary else None,
    }

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from cattle_attention_policy import (
    BASELINE_LOOKBACK_MAX_DAYS,
    BASELINE_REQUIRED_VALID_DAYS,
    FEED_BUNK_ZONE_NAME,
    MAX_OBSERVATION_GAP_SEC,
    MIN_VALID_OBSERVATION_SEC,
    MODEL_VERSION,
    TRACK_CAMERA_ID,
    classify_attention_changes,
)

FARM_TIMEZONE = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")
    return value


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start_local = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        tzinfo=FARM_TIMEZONE,
    )
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _point_in_poly(point: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    count = len(poly)
    if count < 3:
        return False
    for index in range(count):
        x1, y1 = poly[index]
        x2, y2 = poly[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            cross_x = (x2 - x1) * (y - y1) / ((y2 - y1) + 1e-12) + x1
            if x < cross_x:
                inside = not inside
    return inside


def _anchor_point(
    *, x: float, y: float, w: float, h: float, anchor: str
) -> tuple[float, float]:
    anchor = (anchor or "center").lower()
    anchors = {
        "bottom": (x + w / 2, y + h),
        "center": (x + w / 2, y + h / 2),
        "top": (x + w / 2, y),
        "topleft": (x, y),
        "topright": (x + w, y),
    }
    return anchors.get(anchor, anchors["center"])


def _load_feed_bunk_zone(connection: psycopg.Connection) -> dict[str, Any] | None:
    # 현재 track_segment / v_identified_track_observation에는 device_id가 없다.
    # 특정 장비 zone을 선택하면 실제 관측이 그 장비에서 왔는지 검증할 수 없으므로
    # camera A의 전역(device_id IS NULL) feed_bunk zone만 안전하게 사용한다.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, device_id, frame_w, frame_h, poly, anchor
            FROM public.track_zone
            WHERE name = %s
              AND camera_id = %s
              AND device_id IS NULL
              AND is_active = true
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (FEED_BUNK_ZONE_NAME, TRACK_CAMERA_ID),
        )
        row = cursor.fetchone()

    if not row:
        return None

    normalized_poly = row[4] or []
    frame_w = float(row[2] or 0)
    frame_h = float(row[3] or 0)
    if frame_w <= 0 or frame_h <= 0:
        return None

    clean_poly: list[tuple[float, float]] = []
    for point in normalized_poly:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x, y = float(point[0]), float(point[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            continue
        clean_poly.append((x, y))

    if len(clean_poly) < 3:
        return None

    pixel_poly = [(x * frame_w, y * frame_h) for x, y in clean_poly]
    return {
        "id": int(row[0]),
        "device_id": row[1],
        "frame_w": int(row[2]),
        "frame_h": int(row[3]),
        "poly": pixel_poly,
        "anchor": row[5] or "center",
    }


def aggregate_attention_day(
    *,
    national_id: str,
    target_date: date,
    include_test: bool = False,
) -> dict[str, Any]:
    """개체 ID가 연결된 Camera A 관측에서 하루 지표를 계산한다.

    유효 관찰시간은 같은 segment 내 연속 관측의 시간차가 0초 초과,
    MAX_OBSERVATION_GAP_SEC 이하이고 behavior가 비어 있지 않은 구간만 합산한다.
    이 동일한 denominator를 급이대 체류/누움/기립/걷기 비율에 사용한다.
    """

    national_id = str(national_id).strip()
    if not national_id:
        raise ValueError("national_id가 없습니다.")

    start_utc, end_utc = _day_bounds(target_date)

    with psycopg.connect(_database_url()) as connection:
        zone = _load_feed_bunk_zone(connection)

        with connection.cursor() as cursor:
            where = [
                "national_id = %s",
                "camera_id = %s",
                "ts >= %s",
                "ts < %s",
            ]
            params: list[Any] = [national_id, TRACK_CAMERA_ID, start_utc, end_utc]
            if not include_test:
                where.append("session_id NOT LIKE %s")
                params.append("test_%")

            cursor.execute(
                f"""
                SELECT
                    ts,
                    segment_id,
                    track_id,
                    session_id,
                    behavior,
                    behavior_conf,
                    bbox_x,
                    bbox_y,
                    bbox_w,
                    bbox_h
                FROM public.v_identified_track_observation
                WHERE {' AND '.join(where)}
                ORDER BY segment_id, ts
                """,
                params,
            )
            rows = cursor.fetchall()

    segment_rows: dict[int, list[tuple]] = defaultdict(list)
    for row in rows:
        segment_rows[int(row[1])].append(row)

    valid_observation_sec = 0.0
    feed_bunk_duration_sec = 0.0
    lying_duration_sec = 0.0
    standing_duration_sec = 0.0
    walking_duration_sec = 0.0
    used_intervals = 0

    for observations in segment_rows.values():
        observations.sort(key=lambda item: item[0])
        for current, following in zip(observations, observations[1:]):
            delta = (following[0] - current[0]).total_seconds()
            if delta <= 0 or delta > MAX_OBSERVATION_GAP_SEC:
                continue

            behavior = str(current[4] or "").strip().lower()
            if not behavior:
                continue

            bbox = current[6:10]
            if any(value is None for value in bbox):
                continue

            valid_observation_sec += delta
            used_intervals += 1

            if behavior == "lying":
                lying_duration_sec += delta
            elif behavior == "standing":
                standing_duration_sec += delta
            elif behavior == "walking":
                walking_duration_sec += delta

            if zone is not None:
                bx, by, bw, bh = (float(value) for value in bbox)
                point = _anchor_point(
                    x=bx, y=by, w=bw, h=bh, anchor=str(zone["anchor"])
                )
                if _point_in_poly(point, zone["poly"]):
                    feed_bunk_duration_sec += delta

    def ratio(seconds: float) -> float | None:
        if valid_observation_sec <= 0:
            return None
        return seconds / valid_observation_sec

    return {
        "national_id": national_id,
        "analysis_date": target_date.isoformat(),
        "timezone": "Asia/Seoul",
        "camera_id": TRACK_CAMERA_ID,
        "feed_bunk_zone_name": FEED_BUNK_ZONE_NAME,
        "feed_bunk_zone_id": zone["id"] if zone else None,
        "feed_bunk_zone_configured": zone is not None,
        "segments": len(segment_rows),
        "observations": len(rows),
        "used_intervals": used_intervals,
        "valid_observation_sec": round(valid_observation_sec, 3),
        "feed_bunk_duration_sec": round(feed_bunk_duration_sec, 3),
        "feed_bunk_ratio": None if ratio(feed_bunk_duration_sec) is None else round(ratio(feed_bunk_duration_sec), 8),
        "lying_duration_sec": round(lying_duration_sec, 3),
        "lying_ratio": None if ratio(lying_duration_sec) is None else round(ratio(lying_duration_sec), 8),
        "standing_duration_sec": round(standing_duration_sec, 3),
        "standing_ratio": None if ratio(standing_duration_sec) is None else round(ratio(standing_duration_sec), 8),
        "walking_duration_sec": round(walking_duration_sec, 3),
        "walking_ratio": None if ratio(walking_duration_sec) is None else round(ratio(walking_duration_sec), 8),
    }


def _is_valid_day(result: dict[str, Any]) -> bool:
    return (
        result.get("feed_bunk_zone_configured") is True
        and float(result.get("valid_observation_sec") or 0) >= MIN_VALID_OBSERVATION_SEC
        and result.get("feed_bunk_ratio") is not None
        and result.get("lying_ratio") is not None
    )


def build_attention_baseline(
    *,
    national_id: str,
    target_date: date,
    include_test: bool = False,
) -> dict[str, Any]:
    valid_days: list[dict[str, Any]] = []
    checked_days: list[dict[str, Any]] = []

    for offset in range(1, BASELINE_LOOKBACK_MAX_DAYS + 1):
        day = target_date - timedelta(days=offset)
        result = aggregate_attention_day(
            national_id=national_id,
            target_date=day,
            include_test=include_test,
        )
        checked_days.append(result)
        if _is_valid_day(result):
            valid_days.append(result)
        if len(valid_days) >= BASELINE_REQUIRED_VALID_DAYS:
            break

    if len(valid_days) < BASELINE_REQUIRED_VALID_DAYS:
        return {
            "status": "insufficient_baseline",
            "valid_days": len(valid_days),
            "required_valid_days": BASELINE_REQUIRED_VALID_DAYS,
            "minimum_valid_observation_sec": MIN_VALID_OBSERVATION_SEC,
            "checked_calendar_days": len(checked_days),
            "ratios": None,
        }

    selected = valid_days[:BASELINE_REQUIRED_VALID_DAYS]

    def average(key: str) -> float | None:
        values = [float(item[key]) for item in selected if item.get(key) is not None]
        if not values:
            return None
        return mean(values)

    return {
        "status": "ready",
        "valid_days": len(selected),
        "required_valid_days": BASELINE_REQUIRED_VALID_DAYS,
        "minimum_valid_observation_sec": MIN_VALID_OBSERVATION_SEC,
        "checked_calendar_days": len(checked_days),
        "ratios": {
            "feed_bunk": average("feed_bunk_ratio"),
            "lying": average("lying_ratio"),
            "standing": average("standing_ratio"),
            "walking": average("walking_ratio"),
        },
    }


def _change_ratio(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline <= 0:
        return None
    return (current - baseline) / baseline


def evaluate_cattle_attention(
    *,
    national_id: str,
    target_date: date,
    include_test: bool = False,
) -> dict[str, Any]:
    today = aggregate_attention_day(
        national_id=national_id,
        target_date=target_date,
        include_test=include_test,
    )

    if not today["feed_bunk_zone_configured"]:
        return {
            "national_id": national_id,
            "analysis_date": target_date.isoformat(),
            "status": "insufficient_data",
            "primary_metric": None,
            "primary_change_ratio": None,
            "warning_reasons": [],
            "today": today,
            "baseline": None,
            "changes": {},
            "data_quality_reason": (
                f"급이대 ROI '{FEED_BUNK_ZONE_NAME}'가 track_zone에 등록되지 않았습니다."
            ),
            "model_version": MODEL_VERSION,
        }

    if float(today["valid_observation_sec"] or 0) < MIN_VALID_OBSERVATION_SEC:
        return {
            "national_id": national_id,
            "analysis_date": target_date.isoformat(),
            "status": "insufficient_data",
            "primary_metric": None,
            "primary_change_ratio": None,
            "warning_reasons": [],
            "today": today,
            "baseline": None,
            "changes": {},
            "data_quality_reason": (
                "분석에 필요한 유효 관찰시간이 충분하지 않습니다."
            ),
            "model_version": MODEL_VERSION,
        }

    baseline = build_attention_baseline(
        national_id=national_id,
        target_date=target_date,
        include_test=include_test,
    )
    if baseline["status"] != "ready":
        return {
            "national_id": national_id,
            "analysis_date": target_date.isoformat(),
            "status": "insufficient_baseline",
            "primary_metric": None,
            "primary_change_ratio": None,
            "warning_reasons": [],
            "today": today,
            "baseline": baseline,
            "changes": {},
            "data_quality_reason": (
                "비교 기준 계산에 필요한 유효 관찰일이 부족합니다."
            ),
            "model_version": MODEL_VERSION,
        }

    ratios = baseline["ratios"] or {}
    changes = {
        "feed_bunk": _change_ratio(today.get("feed_bunk_ratio"), ratios.get("feed_bunk")),
        "lying": _change_ratio(today.get("lying_ratio"), ratios.get("lying")),
        "standing": _change_ratio(today.get("standing_ratio"), ratios.get("standing")),
        "walking": _change_ratio(today.get("walking_ratio"), ratios.get("walking")),
    }

    decision = classify_attention_changes(
        feed_bunk_change_ratio=changes["feed_bunk"],
        lying_change_ratio=changes["lying"],
    )

    return {
        "national_id": national_id,
        "analysis_date": target_date.isoformat(),
        "status": decision["status"],
        "primary_metric": decision["primary_metric"],
        "primary_change_ratio": decision["primary_change_ratio"],
        "warning_reasons": decision["warning_reasons"],
        "today": today,
        "baseline": baseline,
        "changes": changes,
        "data_quality_reason": None,
        "model_version": MODEL_VERSION,
    }

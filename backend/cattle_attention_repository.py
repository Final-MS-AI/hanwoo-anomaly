from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import psycopg

from cattle_attention_policy import BASELINE_REQUIRED_VALID_DAYS, MODEL_VERSION


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")
    return value


def _cattle_id_for_national_id(connection: psycopg.Connection, national_id: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM public.cattle WHERE national_id = %s LIMIT 1",
            (str(national_id),),
        )
        row = cursor.fetchone()
    if not row:
        raise ValueError(f"cattle에서 national_id={national_id}를 찾을 수 없습니다.")
    return int(row[0])


def _metric_value(result: dict[str, Any], key: str, default: Any = None) -> Any:
    return (result.get("today") or {}).get(key, default)


def _baseline_ratio(result: dict[str, Any], key: str) -> float | None:
    baseline = result.get("baseline") or {}
    ratios = baseline.get("ratios") or {}
    value = ratios.get(key)
    return None if value is None else float(value)


def _change(result: dict[str, Any], key: str) -> float | None:
    value = (result.get("changes") or {}).get(key)
    return None if value is None else float(value)


def upsert_attention_result(
    *,
    result: dict[str, Any],
    source: str = "computed",
) -> dict[str, Any]:
    if source not in {"computed", "demo_simulated"}:
        raise ValueError("source는 computed 또는 demo_simulated만 가능합니다.")

    analysis_date = date.fromisoformat(str(result["analysis_date"]))
    national_id = str(result["national_id"])
    status = str(result["status"])
    model_version = str(result.get("model_version") or MODEL_VERSION)

    with psycopg.connect(_database_url()) as connection:
        cattle_id = _cattle_id_for_national_id(connection, national_id)

        baseline = result.get("baseline") or {}
        baseline_valid_days = int(baseline.get("valid_days") or 0)
        baseline_required_days = int(
            baseline.get("required_valid_days") or BASELINE_REQUIRED_VALID_DAYS
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.cattle_attention_daily_analysis (
                    cattle_id, analysis_date, source, status,
                    primary_metric, primary_change_ratio, warning_reasons,
                    valid_observation_sec,
                    feed_bunk_duration_sec, feed_bunk_ratio,
                    lying_duration_sec, lying_ratio,
                    standing_duration_sec, standing_ratio,
                    walking_duration_sec, walking_ratio,
                    baseline_valid_days, baseline_required_days,
                    baseline_feed_bunk_ratio, baseline_lying_ratio,
                    baseline_standing_ratio, baseline_walking_ratio,
                    feed_bunk_change_ratio, lying_change_ratio,
                    standing_change_ratio, walking_change_ratio,
                    streak_days, data_quality_reason, model_version,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s::jsonb,
                    %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    0, %s, %s,
                    now()
                )
                ON CONFLICT (cattle_id, analysis_date, source, model_version)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    primary_metric = EXCLUDED.primary_metric,
                    primary_change_ratio = EXCLUDED.primary_change_ratio,
                    warning_reasons = EXCLUDED.warning_reasons,
                    valid_observation_sec = EXCLUDED.valid_observation_sec,
                    feed_bunk_duration_sec = EXCLUDED.feed_bunk_duration_sec,
                    feed_bunk_ratio = EXCLUDED.feed_bunk_ratio,
                    lying_duration_sec = EXCLUDED.lying_duration_sec,
                    lying_ratio = EXCLUDED.lying_ratio,
                    standing_duration_sec = EXCLUDED.standing_duration_sec,
                    standing_ratio = EXCLUDED.standing_ratio,
                    walking_duration_sec = EXCLUDED.walking_duration_sec,
                    walking_ratio = EXCLUDED.walking_ratio,
                    baseline_valid_days = EXCLUDED.baseline_valid_days,
                    baseline_required_days = EXCLUDED.baseline_required_days,
                    baseline_feed_bunk_ratio = EXCLUDED.baseline_feed_bunk_ratio,
                    baseline_lying_ratio = EXCLUDED.baseline_lying_ratio,
                    baseline_standing_ratio = EXCLUDED.baseline_standing_ratio,
                    baseline_walking_ratio = EXCLUDED.baseline_walking_ratio,
                    feed_bunk_change_ratio = EXCLUDED.feed_bunk_change_ratio,
                    lying_change_ratio = EXCLUDED.lying_change_ratio,
                    standing_change_ratio = EXCLUDED.standing_change_ratio,
                    walking_change_ratio = EXCLUDED.walking_change_ratio,
                    data_quality_reason = EXCLUDED.data_quality_reason,
                    updated_at = now()
                RETURNING id
                """,
                (
                    cattle_id,
                    analysis_date,
                    source,
                    status,
                    result.get("primary_metric"),
                    result.get("primary_change_ratio"),
                    json.dumps(result.get("warning_reasons") or [], ensure_ascii=False),
                    float(_metric_value(result, "valid_observation_sec", 0) or 0),
                    float(_metric_value(result, "feed_bunk_duration_sec", 0) or 0),
                    _metric_value(result, "feed_bunk_ratio"),
                    float(_metric_value(result, "lying_duration_sec", 0) or 0),
                    _metric_value(result, "lying_ratio"),
                    float(_metric_value(result, "standing_duration_sec", 0) or 0),
                    _metric_value(result, "standing_ratio"),
                    float(_metric_value(result, "walking_duration_sec", 0) or 0),
                    _metric_value(result, "walking_ratio"),
                    baseline_valid_days,
                    baseline_required_days,
                    _baseline_ratio(result, "feed_bunk"),
                    _baseline_ratio(result, "lying"),
                    _baseline_ratio(result, "standing"),
                    _baseline_ratio(result, "walking"),
                    _change(result, "feed_bunk"),
                    _change(result, "lying"),
                    _change(result, "standing"),
                    _change(result, "walking"),
                    result.get("data_quality_reason"),
                    model_version,
                ),
            )
            row_id = int(cursor.fetchone()[0])

            # 해당 source/model의 날짜순 warning streak를 다시 계산한다.
            # 데이터가 빠진 달력일은 streak를 끊는다.
            cursor.execute(
                """
                SELECT id, analysis_date, status
                FROM public.cattle_attention_daily_analysis
                WHERE cattle_id = %s
                  AND source = %s
                  AND model_version = %s
                ORDER BY analysis_date
                """,
                (cattle_id, source, model_version),
            )
            history = cursor.fetchall()

            streak = 0
            previous_date = None
            updates: list[tuple[int, int]] = []
            for history_id, history_date, history_status in history:
                if history_status == "warning":
                    if previous_date is not None and (history_date - previous_date).days == 1:
                        streak += 1
                    else:
                        streak = 1
                else:
                    streak = 0
                updates.append((streak, int(history_id)))
                previous_date = history_date

            cursor.executemany(
                "UPDATE public.cattle_attention_daily_analysis SET streak_days = %s WHERE id = %s",
                updates,
            )

            cursor.execute(
                "SELECT streak_days FROM public.cattle_attention_daily_analysis WHERE id = %s",
                (row_id,),
            )
            streak_days = int(cursor.fetchone()[0])

        connection.commit()

    return {
        "id": row_id,
        "cattle_id": cattle_id,
        "national_id": national_id,
        "analysis_date": analysis_date.isoformat(),
        "status": status,
        "streak_days": streak_days,
        "source": source,
        "model_version": model_version,
    }

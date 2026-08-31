from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from dotenv import dotenv_values
import psycopg

from cattle_attention_policy import (
    BASELINE_REQUIRED_VALID_DAYS,
    MIN_VALID_OBSERVATION_SEC,
    MODEL_VERSION,
    classify_attention_changes,
)
from cattle_attention_repository import upsert_attention_result


# -----------------------------------------------------------------------------
# Demo seed principle
# -----------------------------------------------------------------------------
# The seed defines only daily observation summaries (valid observation seconds
# and behavior/zone ratios). Baseline, change ratios, warning reasons and
# normal/warning status are calculated here with the same policy function used
# by the COWOW daily analysis path. Raw 5-second track observations are not
# fabricated for the presentation.
# -----------------------------------------------------------------------------

METRIC_KEYS = ("feed_bunk", "lying", "standing", "walking")

PROFILE_DEFAULTS = {
    "presentation-3": {"barn_id": "DEMO-FEEDING-ZONE", "status": "active"},
    "presentation-6": {"barn_id": "DEMO-FEEDING-ZONE", "status": "active"},
    "guest-6": {"barn_id": "guest-demo", "status": "demo"},
}


def _row(valid_sec: int, feed_bunk: float, lying: float, standing: float, walking: float) -> dict[str, float]:
    return {
        "valid_observation_sec": float(valid_sec),
        "feed_bunk_ratio": float(feed_bunk),
        "lying_ratio": float(lying),
        "standing_ratio": float(standing),
        "walking_ratio": float(walking),
    }


# Values are ordered oldest -> newest. The newest item is the requested --date.
# feed_bunk is a zone-residence ratio and is independent from the mutually
# exclusive lying/standing/walking behavior ratios.
PRESENTATION_201 = [
    _row(20400, .202, .402, .498, .100),
    _row(21000, .198, .398, .500, .102),
    _row(21600, .201, .401, .500, .099),
    _row(20700, .204, .399, .500, .101),
    _row(21300, .197, .403, .499, .098),
    _row(19800, .200, .400, .500, .100),
    _row(21900, .203, .397, .501, .102),
    _row(20520, .199, .402, .499, .099),
    _row(21120, .201, .401, .498, .101),
    _row(20880, .198, .399, .503, .098),
    _row(21480, .162, .400, .500, .100),
    _row(20880, .158, .398, .501, .101),
    _row(21480, .15384, .400, .500, .100),
]

PRESENTATION_202 = [
    _row(20100, .194, .410, .510, .080),
    _row(20820, .197, .407, .511, .082),
    _row(21480, .195, .412, .509, .079),
    _row(20580, .196, .409, .510, .081),
    _row(21060, .193, .411, .509, .080),
    _row(20340, .198, .408, .511, .081),
    _row(21720, .195, .410, .512, .078),
    _row(20760, .194, .413, .505, .082),
    _row(21360, .197, .409, .512, .079),
    _row(20940, .196, .411, .509, .080),
    _row(21240, .192, .406, .513, .081),
]

PRESENTATION_203 = [
    _row(20640, .186, .398, .512, .090),
    _row(21300, .184, .402, .510, .088),
    _row(20460, .187, .399, .510, .091),
    _row(21660, .185, .401, .510, .089),
    _row(21000, .188, .403, .507, .090),
    _row(20220, .183, .397, .511, .092),
    _row(21540, .186, .400, .511, .089),
    _row(20760, .185, .402, .507, .091),
    _row(21180, .187, .398, .512, .090),
    _row(20880, .184, .400, .512, .088),
    _row(21420, .182, .2672, .6408, .092),
]

# Optional presentation-6 compatibility profile. The first three cows use the
# same presentation scenario; 204/205 are normal and 206 demonstrates cold-start.
PRESENTATION_204 = [
    _row(20400, .205, .398, .505, .097),
    _row(20700, .207, .400, .503, .097),
    _row(21300, .206, .397, .506, .097),
    _row(21000, .204, .401, .502, .097),
    _row(21600, .208, .399, .504, .097),
    _row(20520, .205, .398, .505, .097),
    _row(21240, .207, .400, .503, .097),
    _row(20940, .206, .397, .506, .097),
    _row(21480, .205, .401, .502, .097),
    _row(20760, .207, .399, .504, .097),
    _row(21360, .210, .395, .508, .097),
]
PRESENTATION_205 = [
    _row(20160, .193, .402, .500, .098),
    _row(20940, .195, .404, .498, .098),
    _row(21420, .194, .403, .499, .098),
    _row(20520, .192, .405, .497, .098),
    _row(21240, .196, .401, .501, .098),
    _row(20700, .194, .403, .499, .098),
    _row(21600, .193, .404, .498, .098),
    _row(21060, .195, .402, .500, .098),
    _row(20340, .194, .403, .499, .098),
    _row(21300, .194, .403, .499, .098),
    _row(20700, .192, .400, .502, .098),
]
PRESENTATION_206 = [
    _row(20340, .201, .405, .495, .100),
    _row(20700, .198, .402, .498, .100),
    _row(21180, .200, .404, .496, .100),
    _row(20520, .202, .401, .499, .100),
    _row(21300, .199, .403, .497, .100),
    _row(20880, .201, .404, .496, .100),
    _row(19920, .200, .404, .496, .100),
]

GUEST_001 = [
    _row(20460, .196, .400, .500, .100),
    _row(21000, .194, .402, .499, .099),
    _row(20760, .197, .398, .501, .101),
    _row(21420, .193, .401, .500, .099),
    _row(20280, .195, .403, .498, .099),
    _row(21180, .196, .399, .501, .100),
    _row(20640, .194, .400, .500, .100),
    _row(21600, .195, .402, .497, .101),
    _row(20940, .197, .398, .502, .100),
    _row(21300, .193, .401, .500, .099),
    _row(20400, .157, .398, .502, .100),
]
GUEST_002 = [
    _row(20520, .200, .407, .500, .093),
    _row(21120, .202, .409, .497, .094),
    _row(20880, .203, .406, .500, .094),
    _row(21600, .201, .408, .498, .094),
    _row(20340, .204, .410, .496, .094),
    _row(21240, .200, .407, .499, .094),
    _row(20700, .202, .409, .497, .094),
    _row(21480, .201, .406, .500, .094),
    _row(21000, .203, .408, .498, .094),
    _row(21360, .202, .409, .497, .094),
    _row(21060, .199, .405, .500, .095),
]
GUEST_003 = [
    _row(20040, .188, .398, .512, .090),
    _row(20760, .190, .402, .508, .090),
    _row(21300, .189, .399, .511, .090),
    _row(20400, .191, .401, .509, .090),
    _row(21180, .187, .403, .506, .091),
    _row(20640, .189, .397, .513, .090),
    _row(21540, .190, .400, .510, .090),
    _row(20940, .188, .402, .509, .089),
    _row(21240, .191, .398, .511, .091),
    _row(20580, .187, .400, .510, .090),
    _row(20160, .187, .270, .640, .090),
]
GUEST_004 = [
    _row(20820, .205, .394, .507, .099),
    _row(21420, .207, .396, .505, .099),
    _row(20580, .206, .395, .506, .099),
    _row(21660, .204, .397, .504, .099),
    _row(21000, .208, .393, .508, .099),
    _row(20340, .205, .396, .505, .099),
    _row(21720, .207, .394, .507, .099),
    _row(20760, .206, .395, .506, .099),
    _row(21300, .205, .397, .504, .099),
    _row(20940, .207, .393, .508, .099),
    _row(21540, .210, .391, .510, .099),
]
GUEST_005 = [
    _row(20160, .193, .402, .500, .098),
    _row(20940, .195, .404, .498, .098),
    _row(21420, .194, .403, .499, .098),
    _row(20520, .192, .405, .497, .098),
    _row(21240, .196, .401, .501, .098),
    _row(20700, .194, .403, .499, .098),
    _row(21600, .193, .404, .498, .098),
    _row(21060, .195, .402, .500, .098),
    _row(20340, .194, .403, .499, .098),
    _row(21300, .194, .403, .499, .098),
    _row(20700, .192, .400, .502, .098),
]
GUEST_006 = [
    _row(20340, .201, .405, .495, .100),
    _row(20700, .198, .402, .498, .100),
    _row(21180, .200, .404, .496, .100),
    _row(20520, .202, .401, .499, .100),
    _row(21300, .199, .403, .497, .100),
    _row(20880, .201, .404, .496, .100),
    _row(19920, .200, .404, .496, .100),
]

PROFILE_SERIES: dict[str, dict[str, list[dict[str, float]]]] = {
    "presentation-3": {
        "990000000201": PRESENTATION_201,
        "990000000202": PRESENTATION_202,
        "990000000203": PRESENTATION_203,
    },
    "presentation-6": {
        "990000000201": PRESENTATION_201,
        "990000000202": PRESENTATION_202,
        "990000000203": PRESENTATION_203,
        "990000000204": PRESENTATION_204,
        "990000000205": PRESENTATION_205,
        "990000000206": PRESENTATION_206,
    },
    "guest-6": {
        "990000000001": GUEST_001,
        "990000000002": GUEST_002,
        "990000000003": GUEST_003,
        "990000000004": GUEST_004,
        "990000000005": GUEST_005,
        "990000000006": GUEST_006,
    },
}


def _load_database_url() -> None:
    if os.getenv("DATABASE_URL"):
        return
    for candidate in [
        Path(__file__).resolve().parent / ".env",
        Path("/home/azureuser/3rd_fastapi/.env"),
    ]:
        if candidate.exists():
            value = (dotenv_values(candidate).get("DATABASE_URL") or "").strip()
            if value:
                os.environ["DATABASE_URL"] = value
                return


def _ensure_cattle(
    *,
    user_id: int,
    national_ids: list[str],
    create_missing: bool,
    claim_unassigned: bool,
    barn_id: str,
    cattle_status: str,
    dry_run: bool = False,
) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            for national_id in national_ids:
                cursor.execute(
                    "SELECT id, user_id, barn_id, status FROM public.cattle WHERE national_id = %s LIMIT 1",
                    (national_id,),
                )
                row = cursor.fetchone()
                if row:
                    existing_user_id = row[1]
                    if existing_user_id == user_id:
                        if dry_run:
                            print(
                                f"[dry-run] {national_id}: 기존 cattle 재사용 "
                                f"(id={row[0]}, barn_id={row[2]}, status={row[3]})"
                            )
                        continue
                    if existing_user_id is None and claim_unassigned:
                        if dry_run:
                            print(f"[dry-run] {national_id}: unassigned cattle을 user_id={user_id}로 연결 예정")
                        else:
                            cursor.execute(
                                "UPDATE public.cattle SET user_id = %s, barn_id = COALESCE(barn_id, %s) WHERE id = %s",
                                (user_id, barn_id, row[0]),
                            )
                        continue
                    raise RuntimeError(
                        f"{national_id}는 이미 user_id={existing_user_id} 소유입니다. 강제로 변경하지 않습니다."
                    )

                if not create_missing:
                    raise RuntimeError(
                        f"{national_id}가 없습니다. 추가하려면 --create-missing-cattle을 사용하세요."
                    )

                if dry_run:
                    print(f"[dry-run] {national_id}: user_id={user_id} cattle 신규 생성 예정")
                else:
                    cursor.execute(
                        """
                        INSERT INTO public.cattle (national_id, barn_id, status, user_id)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (national_id, barn_id, cattle_status, user_id),
                    )
        if not dry_run:
            connection.commit()


def _dated_series(target_date: date, rows: list[dict[str, float]]) -> list[dict[str, Any]]:
    start_date = target_date - timedelta(days=len(rows) - 1)
    return [
        {"analysis_date": start_date + timedelta(days=index), **row}
        for index, row in enumerate(rows)
    ]


def _mean(rows: Iterable[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _change(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return (float(current) - float(baseline)) / float(baseline)


def _today_payload(row: dict[str, Any]) -> dict[str, Any]:
    valid_sec = float(row["valid_observation_sec"])
    payload: dict[str, Any] = {"valid_observation_sec": valid_sec}
    for metric in METRIC_KEYS:
        ratio = float(row[f"{metric}_ratio"])
        payload[f"{metric}_ratio"] = ratio
        payload[f"{metric}_duration_sec"] = round(ratio * valid_sec, 3)
    return payload


def _build_result(
    *,
    national_id: str,
    row: dict[str, Any],
    previous_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    current_valid_sec = float(row["valid_observation_sec"])
    today = _today_payload(row)

    if current_valid_sec < MIN_VALID_OBSERVATION_SEC:
        return {
            "national_id": national_id,
            "analysis_date": row["analysis_date"].isoformat(),
            "status": "insufficient_data",
            "primary_metric": None,
            "primary_change_ratio": None,
            "warning_reasons": [],
            "today": today,
            "baseline": {
                "status": "insufficient_data",
                "valid_days": 0,
                "required_valid_days": BASELINE_REQUIRED_VALID_DAYS,
                "ratios": None,
            },
            "changes": {},
            "data_quality_reason": "분석에 필요한 유효 관찰시간이 충분하지 않습니다.",
            "model_version": MODEL_VERSION,
        }

    valid_previous = [
        previous
        for previous in previous_rows
        if float(previous["valid_observation_sec"]) >= MIN_VALID_OBSERVATION_SEC
    ]
    baseline_rows = valid_previous[-BASELINE_REQUIRED_VALID_DAYS:]

    if len(baseline_rows) < BASELINE_REQUIRED_VALID_DAYS:
        return {
            "national_id": national_id,
            "analysis_date": row["analysis_date"].isoformat(),
            "status": "insufficient_baseline",
            "primary_metric": None,
            "primary_change_ratio": None,
            "warning_reasons": [],
            "today": today,
            "baseline": {
                "status": "insufficient_baseline",
                "valid_days": len(baseline_rows),
                "required_valid_days": BASELINE_REQUIRED_VALID_DAYS,
                "ratios": None,
            },
            "changes": {},
            "data_quality_reason": "비교 기준 계산에 필요한 유효 관찰일이 부족합니다.",
            "model_version": MODEL_VERSION,
        }

    baseline_ratios = {
        metric: _mean(baseline_rows, f"{metric}_ratio")
        for metric in METRIC_KEYS
    }
    changes = {
        metric: _change(float(row[f"{metric}_ratio"]), baseline_ratios[metric])
        for metric in METRIC_KEYS
    }
    policy = classify_attention_changes(
        feed_bunk_change_ratio=changes["feed_bunk"],
        lying_change_ratio=changes["lying"],
    )

    return {
        "national_id": national_id,
        "analysis_date": row["analysis_date"].isoformat(),
        "status": policy["status"],
        "primary_metric": policy["primary_metric"],
        "primary_change_ratio": policy["primary_change_ratio"],
        "warning_reasons": policy["warning_reasons"],
        "today": today,
        "baseline": {
            "status": "ready",
            "valid_days": len(baseline_rows),
            "required_valid_days": BASELINE_REQUIRED_VALID_DAYS,
            "ratios": baseline_ratios,
        },
        "changes": changes,
        "data_quality_reason": None,
        "model_version": MODEL_VERSION,
    }


def _profile_results(profile: str, target_date: date) -> dict[str, list[dict[str, Any]]]:
    results: dict[str, list[dict[str, Any]]] = {}
    for national_id, rows in PROFILE_SERIES[profile].items():
        dated_rows = _dated_series(target_date, rows)
        cattle_results: list[dict[str, Any]] = []
        previous_rows: list[dict[str, Any]] = []
        for row in dated_rows:
            cattle_results.append(
                _build_result(
                    national_id=national_id,
                    row=row,
                    previous_rows=previous_rows,
                )
            )
            previous_rows.append(row)
        results[national_id] = cattle_results
    return results


def _delete_existing_demo_rows(national_ids: list[str]) -> None:
    """Delete only demo_simulated rows for the selected profile cattle.

    computed rows and all rows for other cattle are untouched. This prevents a
    previous run with another target date from leaving a newer demo row that
    would take over the dashboard's latest analysis date.
    """
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM public.cattle_attention_daily_analysis a
                USING public.cattle c
                WHERE a.cattle_id = c.id
                  AND c.national_id = ANY(%s)
                  AND a.source = 'demo_simulated'
                  AND a.model_version = %s
                """,
                (national_ids, MODEL_VERSION),
            )
        connection.commit()


def _print_plan(profile: str, target_date: date, results: dict[str, list[dict[str, Any]]]) -> None:
    total_rows = sum(len(items) for items in results.values())
    print(f"profile={profile} date={target_date} cattle={len(results)} daily_rows={total_rows}")
    for national_id, items in results.items():
        target = items[-1]
        change = target.get("primary_change_ratio")
        change_text = "-" if change is None else f"{float(change) * 100:.1f}%"
        baseline = target.get("baseline") or {}
        print(
            f"  {national_id}: {target['status']} "
            f"baseline={baseline.get('valid_days', 0)}/{baseline.get('required_valid_days', BASELINE_REQUIRED_VALID_DAYS)} "
            f"primary={target.get('primary_metric') or '-'} change={change_text}"
        )


def _seed_profile(profile: str, target_date: date) -> None:
    results = _profile_results(profile, target_date)
    national_ids = list(results)
    _delete_existing_demo_rows(national_ids)
    for national_id in national_ids:
        for result in results[national_id]:
            upsert_attention_result(result=result, source="demo_simulated")
    _print_plan(profile, target_date, results)


def main() -> None:
    parser = argparse.ArgumentParser(description="COWOW 왼쪽 대시보드 시연용 일별 집계 seed")
    parser.add_argument("--profile", choices=sorted(PROFILE_SERIES), required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--date", required=True, help="최신 완료 분석일 YYYY-MM-DD")
    parser.add_argument("--create-missing-cattle", action="store_true")
    parser.add_argument("--claim-unassigned", action="store_true")
    parser.add_argument(
        "--barn-id",
        default=None,
        help="미지정 시 profile 기본값 사용(presentation: DEMO-FEEDING-ZONE, guest: guest-demo)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 변경 없이 cattle 소유권과 일별 seed/정책 계산 결과만 검증",
    )
    args = parser.parse_args()

    _load_database_url()
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL을 찾을 수 없습니다.")

    target_date = date.fromisoformat(args.date)
    national_ids = list(PROFILE_SERIES[args.profile])
    profile_defaults = PROFILE_DEFAULTS[args.profile]
    barn_id = args.barn_id or profile_defaults["barn_id"]
    cattle_status = profile_defaults["status"]

    _ensure_cattle(
        user_id=args.user_id,
        national_ids=national_ids,
        create_missing=args.create_missing_cattle,
        claim_unassigned=args.claim_unassigned,
        barn_id=barn_id,
        cattle_status=cattle_status,
        dry_run=args.dry_run,
    )

    results = _profile_results(args.profile, target_date)
    _print_plan(args.profile, target_date, results)

    if args.profile == "presentation-6":
        print("주의: COW-204~206은 실시간 ID 연결 범위와 별개인 시뮬레이션 일별 분석 데이터입니다.")
    if args.profile == "guest-6":
        print("guest-6은 기존 guest-demo COW-001~006을 재사용하며 실제 CCTV 이벤트를 생성하지 않습니다.")

    if args.dry_run:
        print("dry-run 완료: cattle/analysis DB는 변경하지 않았습니다.")
        return

    # A profile re-seed replaces only demo_simulated rows for those cattle.
    # computed/real rows are never deleted.
    _delete_existing_demo_rows(national_ids)
    for national_id in national_ids:
        for result in results[national_id]:
            upsert_attention_result(result=result, source="demo_simulated")

    print("demo_simulated 일별 집계 seed 및 실제 baseline/policy 계산 결과 저장 완료")


if __name__ == "__main__":
    main()

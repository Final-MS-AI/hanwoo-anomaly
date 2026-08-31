from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
import psycopg

from cattle_attention_repository import upsert_attention_result
from cattle_attention_service import evaluate_cattle_attention


def _load_database_url() -> None:
    if os.getenv("DATABASE_URL"):
        return

    candidates = [
        Path(__file__).resolve().parent / ".env",
        Path("/home/azureuser/3rd_fastapi/.env"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        value = (dotenv_values(candidate).get("DATABASE_URL") or "").strip()
        if value:
            os.environ["DATABASE_URL"] = value
            return



FARM_TIMEZONE = ZoneInfo("Asia/Seoul")


def _resolve_target_date(value: str) -> date:
    normalized = str(value or "yesterday").strip().lower()
    if normalized in {"yesterday", "previous-day", "previous_day"}:
        return datetime.now(FARM_TIMEZONE).date() - timedelta(days=1)
    return date.fromisoformat(normalized)


def _national_ids_for_all_active() -> list[str]:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT national_id
                FROM public.cattle
                WHERE COALESCE(status, 'active') = 'active'
                  AND national_id IS NOT NULL
                ORDER BY national_id
                """
            )
            return [str(row[0]) for row in cursor.fetchall()]


def _national_ids_for_user(user_id: int) -> list[str]:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT national_id
                FROM public.cattle
                WHERE user_id = %s
                  AND COALESCE(status, 'active') = 'active'
                  AND national_id IS NOT NULL
                ORDER BY id
                """,
                (user_id,),
            )
            return [str(row[0]) for row in cursor.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="COWOW 왼쪽 일별 주의 분석 실행기"
    )
    parser.add_argument("--date", default="yesterday", help="분석일 YYYY-MM-DD (기본: Asia/Seoul 기준 어제)")
    parser.add_argument("--national-id", action="append", default=[])
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--all-active", action="store_true", help="status=active인 전체 등록 개체 분석")
    parser.add_argument("--include-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    _load_database_url()
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL을 찾을 수 없습니다.")

    target_date = _resolve_target_date(args.date)
    national_ids = [str(value).strip() for value in args.national_id if str(value).strip()]
    if args.user_id is not None:
        national_ids.extend(_national_ids_for_user(args.user_id))
    if args.all_active:
        national_ids.extend(_national_ids_for_all_active())

    national_ids = list(dict.fromkeys(national_ids))
    if not national_ids:
        raise SystemExit("--national-id, --user-id 또는 --all-active 중 하나를 지정하세요.")

    for national_id in national_ids:
        result = evaluate_cattle_attention(
            national_id=national_id,
            target_date=target_date,
            include_test=args.include_test,
        )
        print(
            f"{national_id}: status={result['status']} "
            f"primary={result.get('primary_metric')} "
            f"change={result.get('primary_change_ratio')}"
        )
        if not args.dry_run:
            saved = upsert_attention_result(result=result, source="computed")
            print(
                f"  saved id={saved['id']} streak={saved['streak_days']} "
                f"date={saved['analysis_date']}"
            )


if __name__ == "__main__":
    main()

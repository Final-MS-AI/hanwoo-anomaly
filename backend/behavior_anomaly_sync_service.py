from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import psycopg

from behavior_anomaly_event_service import (
    build_behavior_anomaly_events,
)
from behavior_anomaly_repository import (
    get_database_url,
    resolve_cattle_id,
    resolve_missing_behavior_events,
    upsert_behavior_event,
)
from behavior_anomaly_service import (
    evaluate_cattle_behavior_anomaly,
)


NO_WRITE_STATUSES = {
    "insufficient_data",
    "insufficient_baseline",
}


def sync_cattle_behavior_anomaly(
    *,
    national_id: str,
    target_date: date,
    include_test: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    행동 이상 판정 결과를 anomaly_events와 동기화합니다.

    dry_run=True:
        DB를 변경하지 않습니다.

    dry_run=False:
        anomaly_events INSERT / UPDATE / RESOLVE를 수행합니다.
    """

    anomaly_result = (
        evaluate_cattle_behavior_anomaly(
            national_id=national_id,
            target_date=target_date,
            include_test=include_test,
        )
    )

    overall_status = (
        anomaly_result.get(
            "overall_status"
        )
    )

    if overall_status in NO_WRITE_STATUSES:
        return {
            "national_id": national_id,
            "date": target_date.isoformat(),
            "overall_status": overall_status,
            "dry_run": dry_run,
            "database_action": "skipped",
            "reason": anomaly_result.get(
                "reason"
            ),
            "events": [],
            "resolved_event_ids": [],
            "anomaly_result": anomaly_result,
        }

    cattle_id = resolve_cattle_id(
        national_id
    )

    events = (
        build_behavior_anomaly_events(
            anomaly_result
        )
    )

    active_anomaly_types = {
        str(event["anomaly_type"])
        for event in events
    }

    if dry_run:
        return {
            "national_id": national_id,
            "cattle_id": cattle_id,
            "date": target_date.isoformat(),
            "overall_status": overall_status,
            "dry_run": True,
            "database_action": "dry_run",
            "events": events,
            "active_anomaly_types": sorted(
                active_anomaly_types
            ),
            "resolved_event_ids": [],
            "anomaly_result": anomaly_result,
        }

    now = datetime.now(
        timezone.utc
    )

    upserted_event_ids = []

    with psycopg.connect(
        get_database_url()
    ) as connection:
        try:
            for event in events:
                event_id = (
                    upsert_behavior_event(
                        connection=connection,
                        cattle_id=cattle_id,
                        event=event,
                        detected_at=now,
                    )
                )

                upserted_event_ids.append(
                    event_id
                )

            resolved_event_ids = (
                resolve_missing_behavior_events(
                    connection=connection,
                    cattle_id=cattle_id,
                    active_anomaly_types=(
                        active_anomaly_types
                    ),
                    resolved_at=now,
                )
            )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

    return {
        "national_id": national_id,
        "cattle_id": cattle_id,
        "date": target_date.isoformat(),
        "overall_status": overall_status,
        "dry_run": False,
        "database_action": "committed",
        "events": events,
        "upserted_event_ids": (
            upserted_event_ids
        ),
        "resolved_event_ids": (
            resolved_event_ids
        ),
        "anomaly_result": anomaly_result,
    }

from __future__ import annotations

import json
import os
import shlex
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from dotenv import load_dotenv
from psycopg.rows import dict_row


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
POLICY_PATH = Path(
    os.getenv(
        "FEEDBACK_POLICY_PATH",
        str(BASE_DIR / "feedback_policy_overrides.json"),
    )
)
DEFAULT_POLICY = {
    "lying": {"caution_ratio": 0.30, "anomaly_ratio": 0.50},
    "walking": {"caution_ratio": 0.30, "anomaly_ratio": 0.50},
    "standing": {"caution_ratio": 0.30, "anomaly_ratio": 0.50},
}
POLICY_TYPES = {"false_anomaly", "missed_anomaly"}
BEHAVIOR_TYPES = {"wrong_behavior"}
DETECTION_TYPES = {"false_detection", "missed_cow"}
TRACKING_TYPES = {"wrong_tracking"}


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "")
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    return value


def load_policy() -> dict:
    if not POLICY_PATH.is_file():
        return json.loads(json.dumps(DEFAULT_POLICY))
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def behavior_from_feedback(row: dict) -> str | None:
    value = str(row.get("predicted_label") or "").lower()
    mappings = {
        "long_lying": "lying",
        "lying_decrease": "lying",
        "movement_decrease": "walking",
        "standing_change": "standing",
    }
    if value in DEFAULT_POLICY:
        return value
    return mappings.get(value)


def updated_policy(rows: list[dict], before: dict) -> tuple[dict, bool]:
    after = json.loads(json.dumps(before))
    minimum = int(os.getenv("FEEDBACK_POLICY_MIN_EVENTS", "3"))
    step = min(0.05, max(0.01, float(os.getenv("FEEDBACK_POLICY_STEP", "0.05"))))
    grouped: dict[str, Counter] = {}
    for row in rows:
        behavior = behavior_from_feedback(row)
        if not behavior:
            continue
        grouped.setdefault(behavior, Counter())[row["feedback_type"]] += 1

    changed = False
    for behavior, counts in grouped.items():
        total = counts["false_anomaly"] + counts["missed_anomaly"]
        if total < minimum:
            continue
        direction = 1 if counts["false_anomaly"] > counts["missed_anomaly"] else -1
        current = after.setdefault(behavior, dict(DEFAULT_POLICY[behavior]))
        caution = min(0.80, max(0.10, float(current["caution_ratio"]) + direction * step))
        anomaly = min(0.90, max(caution + 0.10, float(current["anomaly_ratio"]) + direction * step))
        current["caution_ratio"] = round(caution, 4)
        current["anomaly_ratio"] = round(anomaly, 4)
        changed = True
    return after, changed


def upload_manifest(batch_id: str, manifest: dict) -> str:
    account_url = os.getenv(
        "AZURE_STORAGE_ACCOUNT_URL",
        "https://cowimage.blob.core.windows.net",
    )
    container_name = os.getenv("AZURE_ANOMALY_BLOB_CONTAINER", "anomaly-media")
    service = BlobServiceClient(
        account_url=account_url,
        credential=DefaultAzureCredential(),
    )
    container = service.get_container_client(container_name)
    try:
        container.create_container()
    except ResourceExistsError:
        pass
    blob_name = f"feedback-weekly/{batch_id}/manifest.json"
    service.get_blob_client(container_name, blob_name).upload_blob(
        json.dumps(manifest, ensure_ascii=False, default=str, indent=2).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )
    return blob_name


def run_command(template: str, **values: str) -> subprocess.CompletedProcess | None:
    if not template.strip():
        return None
    command = template.format(**{key: shlex.quote(value) for key, value in values.items()})
    return subprocess.run(
        command,
        shell=True,
        check=True,
        text=True,
        capture_output=True,
        timeout=int(os.getenv("FEEDBACK_COMMAND_TIMEOUT_SECONDS", "21600")),
    )


def run_weekly() -> dict:
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=7)
    batch_id = str(uuid.uuid4())
    before = load_policy()

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_xact_lock(2026081801) AS acquired"
            )
            if not cursor.fetchone()["acquired"]:
                return {"status": "skipped", "reason": "another run is active"}
            cursor.execute(
                """
                INSERT INTO feedback_weekly_runs (
                    id, period_started_at, period_ended_at, status, policy_before
                ) VALUES (%s, %s, %s, 'running', %s::jsonb)
                """,
                (batch_id, period_start, now, json.dumps(before)),
            )
            cursor.execute(
                """
                SELECT id, user_id, job_id, anomaly_event_id, event_source,
                       device_id, feedback_type, triage_stage, frame_time_seconds,
                       track_id, predicted_label, corrected_label, comment,
                       evidence_path, evidence_blob_name, inference_summary,
                       feedback_fingerprint, review_status, created_at
                FROM model_feedback
                WHERE weekly_batch_id IS NULL
                  AND created_at <= %s
                ORDER BY created_at
                """,
                (now,),
            )
            rows = [dict(row) for row in cursor.fetchall()]

            policy_candidates = [
                row for row in rows
                if row["feedback_type"] in POLICY_TYPES
                and row.get("anomaly_event_id")
            ]
            minimum = int(os.getenv("FEEDBACK_POLICY_MIN_EVENTS", "3"))
            qualified_policy_ids: list[str] = []
            for behavior in DEFAULT_POLICY:
                behavior_rows = [
                    row for row in policy_candidates
                    if behavior_from_feedback(row) == behavior
                ]
                distinct_events = {
                    row["anomaly_event_id"] for row in behavior_rows
                    if row.get("anomaly_event_id")
                }
                if len(distinct_events) >= minimum:
                    qualified_policy_ids.extend(str(row["id"]) for row in behavior_rows)

            if qualified_policy_ids:
                cursor.execute(
                    """
                    UPDATE model_feedback
                    SET review_status='approved', reviewed_at=NOW(),
                        reviewer_note='weekly consensus auto-approved', updated_at=NOW()
                    WHERE id = ANY(%s::uuid[]) AND review_status='pending'
                    """,
                    (qualified_policy_ids,),
                )
                for row in policy_candidates:
                    if (
                        str(row["id"]) in qualified_policy_ids
                        and row["review_status"] == "pending"
                    ):
                        row["review_status"] = "approved"

            approved = [row for row in rows if row["review_status"] == "approved"]
            policy_rows = [row for row in approved if row["feedback_type"] in POLICY_TYPES]
            after, policy_changed = updated_policy(policy_rows, before)

            manifest = {
                "batch_id": batch_id,
                "created_at": now.isoformat(),
                "period_started_at": period_start.isoformat(),
                "period_ended_at": now.isoformat(),
                "policy_before": before,
                "policy_after": after,
                "policy_changed": policy_changed,
                "feedback": approved,
                "pending_review_count": len(rows) - len(approved),
            }
            blob_name = upload_manifest(batch_id, manifest)

            if policy_changed:
                POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
                temporary = POLICY_PATH.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(after, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(POLICY_PATH)

            behavior_rows = [row for row in approved if row["feedback_type"] in BEHAVIOR_TYPES]
            candidate_path = None
            metrics = None
            promoted_at = None
            minimum_samples = int(os.getenv("FEEDBACK_MODEL_MIN_SAMPLES", "20"))
            train_result = None
            if len(behavior_rows) >= minimum_samples:
                train_result = run_command(
                    os.getenv("FEEDBACK_TRAIN_COMMAND", ""),
                    manifest=blob_name,
                    batch_id=batch_id,
                )
            if train_result is not None:
                candidate_path = train_result.stdout.strip().splitlines()[-1]
                evaluate_result = run_command(
                    os.getenv("FEEDBACK_EVALUATE_COMMAND", ""),
                    manifest=blob_name,
                    batch_id=batch_id,
                    candidate=candidate_path,
                )
                if evaluate_result is not None and evaluate_result.stdout.strip():
                    metrics = json.loads(evaluate_result.stdout.strip().splitlines()[-1])
                if metrics and metrics.get("passed") is True and os.getenv(
                    "FEEDBACK_AUTO_PROMOTE", "false"
                ).lower() == "true":
                    run_command(
                        os.getenv("FEEDBACK_PROMOTE_COMMAND", ""),
                        manifest=blob_name,
                        batch_id=batch_id,
                        candidate=candidate_path,
                    )
                    promoted_at = datetime.now(timezone.utc)

            approved_ids = [str(row["id"]) for row in approved]
            if approved_ids:
                cursor.execute(
                    """
                    UPDATE model_feedback
                    SET weekly_batch_id=%s, training_exported_at=NOW(),
                        review_status='exported', updated_at=NOW()
                    WHERE id = ANY(%s::uuid[])
                    """,
                    (batch_id, approved_ids),
                )

            counts = Counter(row["triage_stage"] for row in rows)
            cursor.execute(
                """
                UPDATE feedback_weekly_runs
                SET status='completed', collected_count=%s, approved_count=%s,
                    policy_feedback_count=%s, behavior_feedback_count=%s,
                    detection_feedback_count=%s, tracking_feedback_count=%s,
                    manifest_blob_name=%s, policy_after=%s::jsonb,
                    candidate_model_path=%s, evaluation_metrics=%s::jsonb,
                    promoted_at=%s, completed_at=NOW()
                WHERE id=%s
                """,
                (
                    len(rows), len(approved), counts["anomaly_policy"],
                    counts["behavior_classifier"], counts["cow_detector"],
                    counts["identity_tracking"], blob_name, json.dumps(after),
                    candidate_path, json.dumps(metrics) if metrics else None,
                    promoted_at, batch_id,
                ),
            )
        connection.commit()

    if policy_changed:
        reload_command = os.getenv("FEEDBACK_RELOAD_COMMAND", "").strip()
        if reload_command:
            subprocess.run(reload_command, shell=True, check=True, timeout=120)

    return {
        "status": "completed",
        "batch_id": batch_id,
        "collected": len(rows),
        "approved": len(approved),
        "policy_changed": policy_changed,
        "manifest_blob_name": blob_name,
        "candidate_model_path": candidate_path,
        "promoted": promoted_at is not None,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(run_weekly(), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        raise

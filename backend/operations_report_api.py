"""Barn operation report API based on persisted IoT telemetry and commands."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import os

from fastapi import APIRouter, Cookie, HTTPException, Query, Response

from device_claim_api import get_connection
from family_device_api import current_user, require_access


router = APIRouter(prefix="/api/reports", tags=["Operations reports"])
PHYSICAL_DEVICE_ID = os.getenv("ESP32_PHYSICAL_DEVICE_ID", "ESP32-01")


def ensure_schema(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS device_telemetry_history (
                id BIGSERIAL PRIMARY KEY,
                device_id TEXT NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                firmware_version TEXT,
                wifi_rssi INTEGER,
                temperature DOUBLE PRECISION,
                humidity DOUBLE PRECISION,
                air_quality DOUBLE PRECISION,
                source TEXT NOT NULL DEFAULT 'iot_hub'
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_device_telemetry_history_lookup
            ON device_telemetry_history(device_id, recorded_at DESC)
            """
        )
    connection.commit()


def number(value):
    return round(float(value), 1) if value is not None else None


def windows(rows, threshold):
    """Return contiguous high-value intervals. Gaps over five minutes split a window."""
    result, current = [], None
    for recorded_at, value in rows:
        if value is None or float(value) < threshold:
            if current:
                result.append(current)
                current = None
            continue
        if current and recorded_at - current["end"] > timedelta(minutes=5):
            result.append(current)
            current = None
        if not current:
            current = {"startedAt": recorded_at, "end": recorded_at, "max": float(value), "samples": 0}
        current["end"] = recorded_at
        current["max"] = max(current["max"], float(value))
        current["samples"] += 1
    if current:
        result.append(current)
    return [
        {
            "startedAt": item["startedAt"].isoformat(),
            "endedAt": item["end"].isoformat(),
            "durationSeconds": int((item["end"] - item["startedAt"]).total_seconds()),
            "maxValue": number(item["max"]),
            "samples": item["samples"],
        }
        for item in result
    ]


def control_durations(rows, end_at):
    """Estimate ON time from completed command transitions; never claim it as device telemetry."""
    by_actuator = defaultdict(list)
    for actuator, command_value, created_at in rows:
        value = command_value
        if isinstance(value, dict):
            value = value.get("value", value.get("level", 0))
        by_actuator[actuator].append((created_at, bool(value and float(value) > 0)))

    result = []
    for actuator, events in by_actuator.items():
        active_since, seconds = None, 0
        for occurred_at, enabled in events:
            if enabled and active_since is None:
                active_since = occurred_at
            elif not enabled and active_since is not None:
                seconds += max(0, int((occurred_at - active_since).total_seconds()))
                active_since = None
        if active_since is not None:
            seconds += max(0, int((end_at - active_since).total_seconds()))
        result.append({
            "actuator": actuator,
            "commandCount": len(events),
            "estimatedOnSeconds": seconds,
            "method": "completed_command_timeline",
        })
    return result


@router.get("/barn")
def barn_report(
    days: int = Query(default=7, ge=1, le=31),
    cowow_session: str | None = Cookie(default=None),
    response: Response = None,
):
    if response is not None:
        response.headers["Cache-Control"] = "no-store, max-age=0"
    user = current_user(cowow_session)
    end_at = datetime.now(timezone.utc)
    start_at = end_at - timedelta(days=days)

    with get_connection() as connection:
        ensure_schema(connection)
        require_access(connection, user, PHYSICAL_DEVICE_ID)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT recorded_at, temperature, humidity, air_quality
                FROM device_telemetry_history
                WHERE device_id = %s AND recorded_at >= %s
                ORDER BY recorded_at ASC
                """,
                (PHYSICAL_DEVICE_ID, start_at),
            )
            telemetry_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    AVG(temperature), MIN(temperature), MAX(temperature),
                    AVG(humidity), MIN(humidity), MAX(humidity),
                    AVG(air_quality), MIN(air_quality), MAX(air_quality),
                    MAX(recorded_at)
                FROM device_telemetry_history
                WHERE device_id = %s AND recorded_at >= %s
                """,
                (PHYSICAL_DEVICE_ID, start_at),
            )
            summary = cursor.fetchone()
            cursor.execute(
                "SELECT last_seen_at FROM device_status WHERE device_id = %s",
                (PHYSICAL_DEVICE_ID,),
            )
            status_row = cursor.fetchone()
            cursor.execute(
                """
                SELECT actuator, command_value, created_at
                FROM device_commands
                WHERE device_id = %s AND status = 'completed' AND created_at >= %s
                ORDER BY created_at ASC
                """,
                (PHYSICAL_DEVICE_ID, start_at),
            )
            command_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT
                    COALESCE(NULLIF(cattle_id, ''), camera_id || ' 미확인 개체') AS cattle_id,
                    behavior, status, COUNT(*) AS count,
                    MIN(detected_at), MAX(detected_at), MAX(confidence)
                FROM device_anomaly_events
                WHERE device_id = %s AND detected_at >= %s
                GROUP BY COALESCE(NULLIF(cattle_id, ''), camera_id || ' 미확인 개체'), behavior, status
                ORDER BY MAX(detected_at) DESC
                LIMIT 50
                """,
                (PHYSICAL_DEVICE_ID, start_at),
            )
            anomaly_rows = cursor.fetchall()

    temperatures = [(row[0], row[1]) for row in telemetry_rows]
    humidities = [(row[0], row[2]) for row in telemetry_rows]
    qualities = [(row[0], row[3]) for row in telemetry_rows]
    last_seen_at = status_row[0] if status_row and status_row[0] else summary[10]
    is_online = bool(last_seen_at and end_at - last_seen_at <= timedelta(minutes=3))
    return {
        "deviceId": PHYSICAL_DEVICE_ID,
        "device": {
            "online": is_online,
            "lastSeenAt": last_seen_at.isoformat() if last_seen_at else None,
        },
        "period": {"startedAt": start_at.isoformat(), "endedAt": end_at.isoformat(), "days": days},
        "telemetry": {
            "sampleCount": int(summary[0] or 0),
            "temperature": {"average": number(summary[1]), "min": number(summary[2]), "max": number(summary[3]), "highWindows": windows(temperatures, 28)},
            "humidity": {"average": number(summary[4]), "min": number(summary[5]), "max": number(summary[6]), "highWindows": windows(humidities, 75)},
            "airQuality": {"average": number(summary[7]), "min": number(summary[8]), "max": number(summary[9]), "highWindows": windows(qualities, 55)},
        },
        "controls": control_durations(command_rows, end_at),
        "anomalies": [
            {
                "cattleId": row[0], "behavior": row[1], "severity": row[2],
                "count": int(row[3]), "firstDetectedAt": row[4].isoformat() if row[4] else None,
                "lastDetectedAt": row[5].isoformat() if row[5] else None,
                "maxConfidence": number(row[6]),
            }
            for row in anomaly_rows
        ],
        "notes": {
            "controlDuration": "가동 시간은 완료된 ON/OFF 제어 명령의 시간차로 계산한 추정치입니다.",
            "history": "센서 이력 수집이 시작된 이후의 데이터만 집계됩니다.",
        },
    }

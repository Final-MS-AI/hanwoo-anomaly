import json
import os
import secrets

import psycopg
from fastapi import APIRouter, Cookie, Header, HTTPException
from pydantic import BaseModel

from auth_session import read_user_id


router = APIRouter(tags=["ESP32 Devices"])

DATABASE_URL = os.getenv("DATABASE_URL", "")
DEMO_DEVICE_ID = os.getenv(
    "ESP32_DEMO_DEVICE_ID",
    "ESP32-DEMO-01",
)
DEMO_SECRET = os.getenv("ESP32_DEMO_SECRET", "")


class ActuatorCommand(BaseModel):
    deviceId: str
    actuator: str
    value: int | bool


class HeartbeatRequest(BaseModel):
    firmwareVersion: str | None = None
    wifiRssi: int | None = None


def verify_device(
    device_id: str,
    supplied_secret: str | None,
):
    if device_id != DEMO_DEVICE_ID:
        raise HTTPException(
            status_code=404,
            detail="등록되지 않은 장치입니다.",
        )

    if (
        not DEMO_SECRET
        or not supplied_secret
        or not secrets.compare_digest(
            supplied_secret,
            DEMO_SECRET,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="장치 인증에 실패했습니다.",
        )


@router.post("/actuators-legacy")
def create_actuator_command(
    body: ActuatorCommand,
    cowow_session: str | None = Cookie(default=None),
):
    user_id = read_user_id(cowow_session)

    if body.deviceId != DEMO_DEVICE_ID:
        raise HTTPException(
            status_code=404,
            detail="등록되지 않은 장치입니다.",
        )

    if body.actuator not in {
        "ventilation_fan",
        "water_sprayer",
    }:
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 제어 장치입니다.",
        )

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO device_commands (
                    device_id,
                    user_id,
                    actuator,
                    command_value,
                    status
                )
                VALUES (%s, %s, %s, %s::jsonb, 'pending')
                RETURNING id, created_at
                """,
                (
                    body.deviceId,
                    user_id,
                    body.actuator,
                    json.dumps(body.value),
                ),
            )
            row = cursor.fetchone()

        connection.commit()

    return {
        "commandId": row[0],
        "status": "pending",
        "createdAt": row[1].isoformat(),
    }


@router.get("/devices/{device_id}/commands/pending")
def get_pending_command(
    device_id: str,
    x_device_secret: str | None = Header(default=None),
):
    verify_device(device_id, x_device_secret)

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, actuator, command_value
                FROM device_commands
                WHERE device_id = %s
                  AND status = 'pending'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (device_id,),
            )
            row = cursor.fetchone()

            if not row:
                return {
                    "command": None,
                }

            cursor.execute(
                """
                UPDATE device_commands
                SET status = 'delivered',
                    delivered_at = NOW()
                WHERE id = %s
                """,
                (row[0],),
            )

        connection.commit()

    return {
        "command": {
            "commandId": row[0],
            "actuator": row[1],
            "value": row[2],
        }
    }


@router.post("/devices/{device_id}/heartbeat")
def heartbeat(
    device_id: str,
    body: HeartbeatRequest,
    x_device_secret: str | None = Header(default=None),
):
    verify_device(device_id, x_device_secret)

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO device_status (
                    device_id,
                    firmware_version,
                    wifi_rssi,
                    last_seen_at
                )
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (device_id)
                DO UPDATE SET
                    firmware_version = EXCLUDED.firmware_version,
                    wifi_rssi = EXCLUDED.wifi_rssi,
                    last_seen_at = NOW()
                """,
                (
                    device_id,
                    body.firmwareVersion,
                    body.wifiRssi,
                ),
            )

        connection.commit()

    return {
        "status": "online",
        "deviceId": device_id,
    }


class TelemetryRequest(BaseModel):
    temperature: float | None = None
    humidity: float | None = None
    airQuality: float | None = None
    ammonia: float | None = None
    carbonDioxide: float | None = None


@router.post("/devices/{device_id}/telemetry")
def save_telemetry(
    device_id: str,
    body: TelemetryRequest,
    x_device_secret: str | None = Header(default=None),
):
    verify_device(device_id, x_device_secret)

    if (
        body.temperature is not None
        and not -40 <= body.temperature <= 80
    ):
        raise HTTPException(
            status_code=400,
            detail="온도값이 허용 범위를 벗어났습니다.",
        )

    if (
        body.humidity is not None
        and not 0 <= body.humidity <= 100
    ):
        raise HTTPException(
            status_code=400,
            detail="습도값이 허용 범위를 벗어났습니다.",
        )

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO device_status (
                    device_id,
                    temperature,
                    humidity,
                    ammonia,
                    carbon_dioxide,
                    telemetry_at,
                    last_seen_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, NOW(), NOW()
                )
                ON CONFLICT (device_id)
                DO UPDATE SET
                    temperature = EXCLUDED.temperature,
                    humidity = EXCLUDED.humidity,
                    ammonia = EXCLUDED.ammonia,
                    carbon_dioxide = EXCLUDED.carbon_dioxide,
                    telemetry_at = NOW(),
                    last_seen_at = NOW()
                RETURNING telemetry_at
                """,
                (
                    device_id,
                    body.temperature,
                    body.humidity,
                    body.airQuality if body.airQuality is not None else body.ammonia,
                    body.carbonDioxide,
                ),
            )
            row = cursor.fetchone()

        connection.commit()

    return {
        "status": "saved",
        "deviceId": device_id,
        "receivedAt": row[0].isoformat(),
    }


@router.get("/devices/{device_id}/state-legacy")
def get_device_state(
    device_id: str,
    cowow_session: str | None = Cookie(default=None),
):
    read_user_id(cowow_session)

    if device_id != DEMO_DEVICE_ID:
        raise HTTPException(
            status_code=404,
            detail="등록되지 않은 장치입니다.",
        )

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    device_id,
                    firmware_version,
                    wifi_rssi,
                    temperature,
                    humidity,
                    ammonia,
                    carbon_dioxide,
                    last_seen_at,
                    telemetry_at,
                    last_seen_at >=
                        NOW() - INTERVAL '30 seconds'
                FROM device_status
                WHERE device_id = %s
                LIMIT 1
                """,
                (device_id,),
            )
            row = cursor.fetchone()

    if not row:
        return {
            "deviceId": device_id,
            "online": False,
            "lastSeenAt": None,
            "telemetryAt": None,
            "sensors": {
                "temperature": None,
                "humidity": None,
                "ammonia": None,
                "carbonDioxide": None,
            },
        }

    return {
        "deviceId": row[0],
        "firmwareVersion": row[1],
        "wifiRssi": row[2],
        "online": bool(row[9]),
        "lastSeenAt": (
            row[7].isoformat()
            if row[7] is not None
            else None
        ),
        "telemetryAt": (
            row[8].isoformat()
            if row[8] is not None
            else None
        ),
        "sensors": {
            "temperature": row[3],
            "humidity": row[4],
            "ammonia": row[5],
            "carbonDioxide": row[6],
        },
    }


class DeviceClaimRequest(BaseModel):
    deviceId: str
    claimCode: str
    barnName: str | None = None
    networkName: str | None = None


@router.post("/devices/claim-legacy")
def claim_device(
    body: DeviceClaimRequest,
    cowow_session: str | None = Cookie(default=None),
):
    user_id = read_user_id(cowow_session)

    expected_code = os.getenv(
        "ESP32_DEMO_CLAIM_CODE",
        "DEMO-2026",
    )

    if body.deviceId != DEMO_DEVICE_ID:
        raise HTTPException(
            status_code=404,
            detail="등록되지 않은 장비 ID입니다.",
        )

    if not secrets.compare_digest(
        body.claimCode.strip(),
        expected_code,
    ):
        raise HTTPException(
            status_code=400,
            detail="일회용 등록 코드가 올바르지 않습니다.",
        )

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registered_devices (
                    device_id,
                    user_id,
                    barn_name,
                    network_name
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (device_id)
                DO UPDATE SET
                    barn_name = EXCLUDED.barn_name,
                    network_name = EXCLUDED.network_name,
                    updated_at = NOW()
                WHERE registered_devices.user_id =
                    EXCLUDED.user_id
                RETURNING
                    device_id,
                    barn_name,
                    network_name,
                    claimed_at
                """,
                (
                    body.deviceId,
                    user_id,
                    body.barnName,
                    body.networkName,
                ),
            )
            row = cursor.fetchone()

        connection.commit()

    if not row:
        raise HTTPException(
            status_code=409,
            detail="이미 다른 계정에 등록된 장비입니다.",
        )

    return {
        "device": {
            "deviceId": row[0],
            "deviceName": f"ESP32 {row[0]}",
            "barnName": row[1],
            "networkName": row[2],
            "claimedAt": row[3].isoformat(),
        }
    }

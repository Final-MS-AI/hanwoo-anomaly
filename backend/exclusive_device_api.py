import os

import psycopg
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from device_claim_api import (
    CLAIM_CODE_EXPIRE_MINUTES,
    generate_code,
    get_connection,
    get_user,
    hash_code,
    mask_email,
    normalize_code,
    require_user,
    send_claim_email,
)


router = APIRouter(tags=["Exclusive device registration"])

PHYSICAL_DEVICE_ID = os.getenv(
    "ESP32_PHYSICAL_DEVICE_ID",
    "ESP32-01",
)
PUBLIC_DEVICE_NUMBER = os.getenv(
    "ESP32_PUBLIC_DEVICE_NUMBER",
    "COWOW-0001",
)


class ClaimCodeSendRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=100)


class ExclusiveClaimRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=100)
    claimCode: str = Field(min_length=1, max_length=40)
    barnName: str = Field(default="1번 축사", max_length=100)


def normalize_device_number(value: str):
    return value.strip().upper()


def require_public_device_number(value: str):
    normalized = normalize_device_number(value)

    if normalized != PUBLIC_DEVICE_NUMBER:
        raise HTTPException(
            status_code=404,
            detail="등록되지 않은 장비 번호입니다.",
        )

    return normalized


def find_owner(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                owner.user_id,
                users.provider,
                users.name
            FROM device_owners owner
            LEFT JOIN users
                ON users.id = owner.user_id
            WHERE owner.device_id = %s
            """,
            (PHYSICAL_DEVICE_ID,),
        )
        return cursor.fetchone()


def ensure_physical_device(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cowow_devices (
                device_id,
                device_name,
                is_active
            )
            VALUES (%s, %s, TRUE)
            ON CONFLICT (device_id)
            DO UPDATE SET
                device_name = EXCLUDED.device_name,
                is_active = TRUE
            """,
            (
                PHYSICAL_DEVICE_ID,
                "COWOW ESP32-01",
            ),
        )


@router.post("/devices/claim-code/send")
def send_exclusive_claim_code(
    body: ClaimCodeSendRequest,
    cowow_session: str | None = Cookie(default=None),
):
    user_id = require_user(cowow_session)
    require_public_device_number(body.deviceId)

    with get_connection() as connection:
        user = get_user(connection, user_id)

        if user["provider"] == "guest":
            raise HTTPException(
                status_code=400,
                detail="게스트는 guest 코드를 사용해 주세요.",
            )

        if not user["email"]:
            raise HTTPException(
                status_code=400,
                detail="로그인 계정에 이메일 정보가 없습니다.",
            )

        ensure_physical_device(connection)
        owner = find_owner(connection)

        if owner and owner[0] != user_id:
            raise HTTPException(
                status_code=409,
                detail="현재 다른 사용자가 사용 중인 장비입니다.",
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT device_id
                FROM device_owners
                WHERE user_id = %s
                  AND device_id <> %s
                LIMIT 1
                """,
                (
                    user_id,
                    PHYSICAL_DEVICE_ID,
                ),
            )

            if cursor.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="이 계정에는 이미 다른 장비가 연결되어 있습니다.",
                )

            code = generate_code()

            cursor.execute(
                """
                UPDATE device_claim_codes
                SET used_at = NOW()
                WHERE user_id = %s
                  AND used_at IS NULL
                """,
                (user_id,),
            )

            cursor.execute(
                """
                INSERT INTO device_claim_codes (
                    user_id,
                    device_id,
                    code_hash,
                    expires_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    NOW() + (%s * INTERVAL '1 minute')
                )
                """,
                (
                    user_id,
                    PHYSICAL_DEVICE_ID,
                    hash_code(code),
                    CLAIM_CODE_EXPIRE_MINUTES,
                ),
            )

        connection.commit()

    send_claim_email(
        user["email"],
        user["name"],
        code,
    )

    return {
        "message": (
            f"{mask_email(user['email'])}로 등록 코드를 보냈습니다. "
            f"{CLAIM_CODE_EXPIRE_MINUTES}분 안에 입력해 주세요."
        ),
        "deviceNumber": PUBLIC_DEVICE_NUMBER,
        "expiresInMinutes": CLAIM_CODE_EXPIRE_MINUTES,
    }


@router.post("/devices/claim")
def claim_exclusive_device(
    body: ExclusiveClaimRequest,
    cowow_session: str | None = Cookie(default=None),
):
    user_id = require_user(cowow_session)
    requested_number = normalize_device_number(body.deviceId)
    requested_code = normalize_code(body.claimCode)

    with get_connection() as connection:
        user = get_user(connection, user_id)
        ensure_physical_device(connection)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT device_id
                FROM cowow_devices
                WHERE device_id = %s
                FOR UPDATE
                """,
                (PHYSICAL_DEVICE_ID,),
            )
            cursor.fetchone()

            owner = find_owner(connection)

            if user["provider"] == "guest":
                if (
                    requested_number != "GUEST"
                    or requested_code != "GUEST"
                ):
                    raise HTTPException(
                        status_code=400,
                        detail="게스트 장비 번호와 등록 코드는 guest입니다.",
                    )

                if owner:
                    raise HTTPException(
                        status_code=409,
                        detail="현재 다른 사용자가 사용 중인 장비입니다.",
                    )

                return {
                    "device": {
                        "deviceId": PHYSICAL_DEVICE_ID,
                        "publicDeviceNumber": "guest",
                        "deviceName": "게스트 데모 장비",
                        "barnName": body.barnName or "게스트 축사",
                        "role": "guest",
                        "guest": True,
                    }
                }

            require_public_device_number(requested_number)

            if owner and owner[0] != user_id:
                raise HTTPException(
                    status_code=409,
                    detail="현재 다른 사용자가 사용 중인 장비입니다.",
                )

            cursor.execute(
                """
                SELECT
                    id,
                    expires_at > NOW() AS valid_time,
                    attempts
                FROM device_claim_codes
                WHERE user_id = %s
                  AND device_id = %s
                  AND code_hash = %s
                  AND used_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (
                    user_id,
                    PHYSICAL_DEVICE_ID,
                    hash_code(requested_code),
                ),
            )
            claim_row = cursor.fetchone()

            if not claim_row:
                cursor.execute(
                    """
                    UPDATE device_claim_codes
                    SET attempts = attempts + 1
                    WHERE user_id = %s
                      AND device_id = %s
                      AND used_at IS NULL
                      AND expires_at > NOW()
                    """,
                    (
                        user_id,
                        PHYSICAL_DEVICE_ID,
                    ),
                )
                connection.commit()

                raise HTTPException(
                    status_code=400,
                    detail="등록 코드가 올바르지 않습니다.",
                )

            claim_id, valid_time, attempts = claim_row

            if not valid_time:
                raise HTTPException(
                    status_code=400,
                    detail="등록 코드가 만료되었습니다. 새 코드를 받아 주세요.",
                )

            if attempts >= 5:
                raise HTTPException(
                    status_code=429,
                    detail="입력 횟수를 초과했습니다. 새 코드를 받아 주세요.",
                )

            cursor.execute(
                """
                SELECT device_id
                FROM device_owners
                WHERE user_id = %s
                  AND device_id <> %s
                LIMIT 1
                """,
                (
                    user_id,
                    PHYSICAL_DEVICE_ID,
                ),
            )

            if cursor.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="이 계정에는 이미 다른 장비가 연결되어 있습니다.",
                )

            cursor.execute(
                """
                INSERT INTO device_owners (
                    device_id,
                    user_id,
                    barn_name
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (device_id)
                DO NOTHING
                RETURNING device_id
                """,
                (
                    PHYSICAL_DEVICE_ID,
                    user_id,
                    body.barnName or "1번 축사",
                ),
            )
            inserted = cursor.fetchone()

            if not inserted and not (
                owner and owner[0] == user_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="현재 다른 사용자가 사용 중인 장비입니다.",
                )

            if owner and owner[0] == user_id:
                cursor.execute(
                    """
                    UPDATE device_owners
                    SET
                        barn_name = %s,
                        updated_at = NOW()
                    WHERE device_id = %s
                      AND user_id = %s
                    """,
                    (
                        body.barnName or "1번 축사",
                        PHYSICAL_DEVICE_ID,
                        user_id,
                    ),
                )

            cursor.execute(
                """
                UPDATE device_claim_codes
                SET used_at = NOW()
                WHERE id = %s
                """,
                (claim_id,),
            )

        connection.commit()

    return {
        "device": {
            "deviceId": PHYSICAL_DEVICE_ID,
            "publicDeviceNumber": PUBLIC_DEVICE_NUMBER,
            "deviceName": "COWOW ESP32-01",
            "barnName": body.barnName or "1번 축사",
            "role": "owner",
            "guest": False,
        }
    }

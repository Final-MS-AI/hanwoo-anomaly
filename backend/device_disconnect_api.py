import os

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, Field

from auth_session import read_user_id


router = APIRouter(tags=["Device connection"])

DATABASE_URL = os.getenv("DATABASE_URL", "")


class DisconnectDeviceRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=100)


def require_user(cowow_session: str | None):
    if not cowow_session:
        raise HTTPException(
            status_code=401,
            detail="Login is required.",
        )

    try:
        user_id = read_user_id(cowow_session)
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail="The login session has expired.",
        ) from exc

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Login is required.",
        )

    return user_id


@router.delete(
    "/devices/connection-legacy",
    status_code=204,
)
def disconnect_device(
    body: DisconnectDeviceRequest,
    cowow_session: str | None = Cookie(default=None),
):
    user_id = require_user(cowow_session)

    if not DATABASE_URL:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL is not configured.",
        )

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT provider
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            user_row = cursor.fetchone()

            if not user_row:
                raise HTTPException(
                    status_code=401,
                    detail="User account was not found.",
                )

            provider = user_row[0]

            # Guest access does not store permanent ownership.
            if provider == "guest":
                connection.commit()
                return Response(status_code=204)

            cursor.execute(
                """
                DELETE FROM device_owners
                WHERE user_id = %s
                  AND device_id = %s
                RETURNING device_id
                """,
                (
                    user_id,
                    body.deviceId.strip(),
                ),
            )
            deleted_row = cursor.fetchone()

            if not deleted_row:
                connection.commit()
                return Response(status_code=204)

            cursor.execute(
                """
                UPDATE device_claim_codes
                SET used_at = NOW()
                WHERE user_id = %s
                  AND device_id = %s
                  AND used_at IS NULL
                """,
                (
                    user_id,
                    body.deviceId.strip(),
                ),
            )

        connection.commit()

    return Response(status_code=204)

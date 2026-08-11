import os

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

router = APIRouter(prefix="/auth", tags=["Authentication"])

COOKIE_NAME = "cowow_session"
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "604800"))
COOKIE_SECURE = os.getenv(
    "SESSION_COOKIE_SECURE", "true"
).lower() == "true"


def serializer():
    if not SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET이 설정되지 않았습니다.")

    return URLSafeTimedSerializer(
        SESSION_SECRET,
        salt="cowow-login-session",
    )


def create_session_cookie(response: Response, user_id: int):
    token = serializer().dumps({"user_id": int(user_id)})

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="none" if COOKIE_SECURE else "lax",
        path="/",
    )


def read_user_id(token: str | None):
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")

    try:
        payload = serializer().loads(
            token,
            max_age=SESSION_MAX_AGE,
        )
        return int(payload["user_id"])
    except SignatureExpired as exc:
        raise HTTPException(
            401, "로그인 세션이 만료되었습니다."
        ) from exc
    except (BadSignature, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            401, "유효하지 않은 로그인 세션입니다."
        ) from exc


@router.get("/me")
def me(cowow_session: str | None = Cookie(default=None)):
    user_id = read_user_id(cowow_session)
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise HTTPException(
            500, "DATABASE_URL이 설정되지 않았습니다."
        )

    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, provider, provider_user_id,
                           name, email, profile_image_url
                    FROM users
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
    except psycopg.Error as exc:
        raise HTTPException(
            500, "사용자 조회에 실패했습니다."
        ) from exc

    if not row:
        raise HTTPException(
            401, "사용자를 찾을 수 없습니다."
        )

    return {
        "user": {
            "id": row[0],
            "provider": row[1],
            "provider_user_id": row[2],
            "name": row[3],
            "email": row[4],
            "profile_image_url": row[5],
        }
    }


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="none" if COOKIE_SECURE else "lax",
        path="/",
    )

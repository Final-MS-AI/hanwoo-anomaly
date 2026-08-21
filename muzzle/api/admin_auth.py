"""muzzle 트랙 API의 관리자 세션 보호."""
import os

import psycopg
from fastapi import Cookie, HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "cowow_session"
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "604800"))


def _read_user_id(token: str | None):
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")
    secret = os.getenv("SESSION_SECRET", "")
    if not secret:
        raise HTTPException(500, "SESSION_SECRET이 설정되지 않았습니다.")
    try:
        payload = URLSafeTimedSerializer(secret, salt="cowow-login-session").loads(token, max_age=SESSION_MAX_AGE)
        return int(payload["user_id"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(401, "유효하지 않은 로그인 세션입니다.") from exc


def require_admin(cowow_session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    user_id = _read_user_id(cowow_session)
    emails = {value.strip().lower() for value in os.getenv("ADMIN_EMAILS", "").split(",") if value.strip()}
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        row = connection.execute("SELECT id, email FROM public.users WHERE id=%s LIMIT 1", (user_id,)).fetchone()
        is_admin = bool(connection.execute("SELECT 1 FROM public.admin_users WHERE user_id=%s", (user_id,)).fetchone())
    if row and row[1] and row[1].strip().lower() in emails:
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            connection.execute("INSERT INTO public.admin_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
            connection.commit()
        is_admin = True
    if not row or not is_admin:
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return {"id": row[0], "email": row[1]}

"""테스트용 공용 관리자 로그인."""
import os
import secrets

import psycopg
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from auth_session import create_session_cookie

router = APIRouter(prefix="/auth", tags=["Authentication"])


class AdminLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/admin-login")
def admin_login(body: AdminLoginRequest):
    configured_username = os.getenv("ADMIN_USERNAME", "")
    configured_password = os.getenv("ADMIN_PASSWORD", "")
    if not configured_username or not configured_password:
        raise HTTPException(503, "테스트 관리자 로그인이 설정되지 않았습니다.")
    if not (secrets.compare_digest(body.username, configured_username) and secrets.compare_digest(body.password, configured_password)):
        raise HTTPException(401, "관리자 아이디 또는 비밀번호가 올바르지 않습니다.")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(500, "DATABASE_URL이 설정되지 않았습니다.")
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """INSERT INTO public.users (provider, provider_user_id, name, email)
               VALUES ('admin', %s, '테스트 관리자', %s)
               ON CONFLICT (provider, provider_user_id) DO UPDATE SET updated_at=NOW()
               RETURNING id, provider, provider_user_id, name, email, profile_image_url""",
            (configured_username, f"{configured_username}@admin.local"),
        ).fetchone()
        connection.execute("INSERT INTO public.admin_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (row[0],))
        connection.commit()

    response = Response(content=__import__("json").dumps({
        "id": row[0], "provider": row[1], "provider_user_id": row[2], "name": row[3], "email": row[4], "profile_image_url": row[5],
    }), media_type="application/json")
    create_session_cookie(response, row[0])
    return response

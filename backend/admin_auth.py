"""관리자 권한 확인.

관리자 이메일은 ADMIN_EMAILS 환경 변수에 쉼표로 지정한다.
예: ADMIN_EMAILS=admin@example.com,owner@example.com
허용 목록이 비어 있으면 관리자 권한을 발급하지 않는다.
"""
import os

import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query

from auth_session import COOKIE_NAME, read_user_id
from admin_notification_store import create_admin_notification

router = APIRouter(prefix="/admin", tags=["Admin"])


def _admin_emails():
    return {
        value.strip().lower()
        for value in os.getenv("ADMIN_EMAILS", "").split(",")
        if value.strip()
    }


def require_admin(cowow_session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    user_id = read_user_id(cowow_session)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(500, "DATABASE_URL이 설정되지 않았습니다.")

    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT id, provider, name, email FROM public.users WHERE id=%s LIMIT 1",
            (user_id,),
        ).fetchone()
        is_admin = bool(connection.execute(
            "SELECT 1 FROM public.admin_users WHERE user_id=%s", (user_id,)
        ).fetchone())

    if row and row[3] and row[3].strip().lower() in _admin_emails():
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "INSERT INTO public.admin_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (user_id,),
            )
            connection.commit()
        is_admin = True

    if not row or not is_admin:
        raise HTTPException(403, "관리자 권한이 필요합니다.")

    return {"id": row[0], "provider": row[1], "name": row[2], "email": row[3]}


@router.get("/me")
def admin_me(admin=Depends(require_admin)):
    return {"admin": admin}


@router.get("/users")
def list_admin_users(admin=Depends(require_admin)):
    database_url = os.getenv("DATABASE_URL")
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """SELECT u.id, u.name, u.email, a.granted_at
               FROM public.admin_users a JOIN public.users u ON u.id=a.user_id
               ORDER BY a.granted_at"""
        ).fetchall()
    return {"users": [{"id": r[0], "name": r[1], "email": r[2], "granted_at": r[3]} for r in rows]}


@router.post("/users/{user_id}")
def grant_admin(user_id: int, admin=Depends(require_admin)):
    database_url = os.getenv("DATABASE_URL")
    with psycopg.connect(database_url) as connection:
        if not connection.execute("SELECT 1 FROM public.users WHERE id=%s", (user_id,)).fetchone():
            raise HTTPException(404, "사용자를 찾을 수 없습니다.")
        connection.execute(
            "INSERT INTO public.admin_users (user_id, granted_by) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (user_id, admin["id"]),
        )
        connection.commit()
    create_admin_notification(
        "admin_granted",
        "관리자 권한이 추가되었습니다",
        f"{user_id}번 사용자에게 관리자 권한을 부여했습니다.",
        severity="success",
        event_key=f"admin-granted:{user_id}",
    )
    return {"user_id": user_id, "status": "admin"}


@router.post("/users/by-email")
def grant_admin_by_email(email: str = Query(..., min_length=3), admin=Depends(require_admin)):
    database_url = os.getenv("DATABASE_URL")
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT id FROM public.users WHERE lower(email)=lower(%s) LIMIT 1", (email.strip(),)
        ).fetchone()
    if not row:
        raise HTTPException(404, "해당 이메일로 가입한 사용자를 찾을 수 없습니다.")
    return grant_admin(row[0], admin)


@router.delete("/users/{user_id}")
def revoke_admin(user_id: int, admin=Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "자기 자신의 관리자 권한은 해제할 수 없습니다.")
    database_url = os.getenv("DATABASE_URL")
    with psycopg.connect(database_url) as connection:
        deleted = connection.execute("DELETE FROM public.admin_users WHERE user_id=%s", (user_id,)).rowcount
        connection.commit()
    if not deleted:
        raise HTTPException(404, "관리자를 찾을 수 없습니다.")
    create_admin_notification(
        "admin_revoked",
        "관리자 권한이 해제되었습니다",
        f"{user_id}번 사용자의 관리자 권한을 해제했습니다.",
        severity="warning",
        event_key=None,
    )
    return {"user_id": user_id, "status": "revoked"}

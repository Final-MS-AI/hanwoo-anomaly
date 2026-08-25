"""관리자 권한 확인.

관리자 이메일은 ADMIN_EMAILS 환경 변수에 쉼표로 지정한다.
예: ADMIN_EMAILS=admin@example.com,owner@example.com
허용 목록이 비어 있으면 관리자 권한을 발급하지 않는다.
"""
import os

import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from psycopg.rows import dict_row

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
            """SELECT u.id, u.name, u.email, u.provider, a.granted_at
               FROM public.admin_users a JOIN public.users u ON u.id=a.user_id
               ORDER BY a.granted_at"""
        ).fetchall()
    return {
        "can_revoke": admin["provider"] == "admin",
        "users": [{"id": r[0], "name": r[1], "email": r[2], "provider": r[3], "granted_at": r[4]} for r in rows],
    }


@router.get("/data/users")
def list_data_users(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=200),
    admin=Depends(require_admin),
):
    """List application users with developer-facing data totals."""
    database_url = os.getenv("DATABASE_URL")
    normalized = q.strip().lower() if q and q.strip() else None
    pattern = f"%{normalized}%" if normalized else None
    search_clause = ""
    parameters: tuple = (limit,)
    if normalized:
        search_clause = """WHERE (LOWER(COALESCE(u.name, '')) LIKE %s
                              OR LOWER(COALESCE(u.email, '')) LIKE %s
                              OR u.id::text = %s)"""
        parameters = (pattern, pattern, normalized, limit)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            f"""
            WITH cattle_totals AS (
                SELECT user_id, COUNT(*) AS cattle_count
                  FROM public.cattle GROUP BY user_id
            ), device_totals AS (
                SELECT user_id, COUNT(DISTINCT device_id) AS device_count
                  FROM (
                      SELECT user_id, device_id FROM public.device_owners
                      UNION ALL
                      SELECT user_id, device_id FROM public.device_members
                  ) linked GROUP BY user_id
            ), feedback_totals AS (
                SELECT user_id, COUNT(*) AS feedback_count
                  FROM public.model_feedback GROUP BY user_id
            ), anomaly_totals AS (
                SELECT c.user_id, COUNT(*) AS anomaly_count
                  FROM public.anomaly_events ae
                  JOIN public.cattle c ON c.id=ae.cattle_id
                 GROUP BY c.user_id
            )
            SELECT u.id, u.name, u.email, u.provider, u.created_at,
                   (a.user_id IS NOT NULL) AS is_admin,
                   COALESCE(ct.cattle_count, 0) AS cattle_count,
                   COALESCE(dt.device_count, 0) AS device_count,
                   COALESCE(ft.feedback_count, 0) AS feedback_count,
                   COALESCE(at.anomaly_count, 0) AS anomaly_count
              FROM public.users u
              LEFT JOIN public.admin_users a ON a.user_id=u.id
              LEFT JOIN cattle_totals ct ON ct.user_id=u.id
              LEFT JOIN device_totals dt ON dt.user_id=u.id
              LEFT JOIN feedback_totals ft ON ft.user_id=u.id
              LEFT JOIN anomaly_totals at ON at.user_id=u.id
              {search_clause}
             ORDER BY u.created_at DESC, u.id DESC
             LIMIT %s
            """,
            parameters,
        ).fetchall()
    return {"users": [dict(row) for row in rows], "count": len(rows)}


@router.get("/data/users/{user_id}")
def get_data_user(user_id: int, admin=Depends(require_admin)):
    """Return cattle, devices, feedback and anomaly data for one user."""
    database_url = os.getenv("DATABASE_URL")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            SELECT jsonb_build_object(
                'user', jsonb_build_object(
                    'id', u.id, 'name', u.name, 'email', u.email,
                    'provider', u.provider, 'created_at', u.created_at,
                    'is_admin', EXISTS (
                        SELECT 1 FROM public.admin_users a WHERE a.user_id=u.id
                    )
                ),
                'summary', jsonb_build_object(
                    'cattle', (SELECT COUNT(*) FROM public.cattle c WHERE c.user_id=u.id),
                    'devices', (SELECT COUNT(DISTINCT device_id) FROM (
                        SELECT o.device_id FROM public.device_owners o WHERE o.user_id=u.id
                        UNION ALL
                        SELECT m.device_id FROM public.device_members m WHERE m.user_id=u.id
                    ) linked),
                    'feedback', (SELECT COUNT(*) FROM public.model_feedback f WHERE f.user_id=u.id),
                    'anomalies', (SELECT COUNT(*) FROM public.anomaly_events ae
                        JOIN public.cattle c ON c.id=ae.cattle_id WHERE c.user_id=u.id),
                    'active_anomalies', (SELECT COUNT(*) FROM public.anomaly_events ae
                        JOIN public.cattle c ON c.id=ae.cattle_id
                        WHERE c.user_id=u.id AND ae.is_active)
                ),
                'cattle', COALESCE((SELECT jsonb_agg(to_jsonb(items) ORDER BY items.created_at DESC)
                    FROM (SELECT c.id, c.national_id, c.ear_tag_number, c.barn_id,
                                 c.status, c.created_at, COUNT(ae.id) AS anomaly_count,
                                 COUNT(ae.id) FILTER (WHERE ae.is_active) AS active_anomaly_count,
                                 MAX(ae.detected_at) AS last_anomaly_at
                            FROM public.cattle c
                            LEFT JOIN public.anomaly_events ae ON ae.cattle_id=c.id
                           WHERE c.user_id=u.id GROUP BY c.id) items), '[]'::jsonb),
                'devices', COALESCE((SELECT jsonb_agg(to_jsonb(items) ORDER BY items.connected_at DESC)
                    FROM (SELECT o.device_id, 'owner'::text AS role, o.registered_at AS connected_at
                            FROM public.device_owners o WHERE o.user_id=u.id
                          UNION ALL
                          SELECT m.device_id, 'member'::text AS role, m.joined_at AS connected_at
                            FROM public.device_members m WHERE m.user_id=u.id) items), '[]'::jsonb),
                'feedback', COALESCE((SELECT jsonb_agg(to_jsonb(items) ORDER BY items.created_at DESC)
                    FROM (SELECT id, feedback_type, predicted_label, corrected_label,
                                 review_status, triage_stage, created_at, reviewed_at
                            FROM public.model_feedback WHERE user_id=u.id
                           ORDER BY created_at DESC LIMIT 30) items), '[]'::jsonb),
                'anomalies', COALESCE((SELECT jsonb_agg(to_jsonb(items) ORDER BY items.detected_at DESC)
                    FROM (SELECT ae.id, c.national_id, ae.anomaly_type, ae.severity,
                                 ae.score, ae.message, ae.is_active, ae.detected_at
                            FROM public.anomaly_events ae
                            JOIN public.cattle c ON c.id=ae.cattle_id
                           WHERE c.user_id=u.id
                           ORDER BY ae.detected_at DESC, ae.id DESC LIMIT 30) items), '[]'::jsonb)
            ) AS payload
            FROM public.users u
            WHERE u.id=%s
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    return row["payload"]


@router.get("/data/identity/owners")
def list_identity_owners(admin=Depends(require_admin)):
    """Return user ownership data used to scope tracks and bindings."""
    database_url = os.getenv("DATABASE_URL")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            WITH cattle_ids AS (
                SELECT user_id,
                       array_agg(DISTINCT national_id::text) FILTER (WHERE national_id IS NOT NULL) AS national_ids
                  FROM public.cattle
                 GROUP BY user_id
            ), linked_devices AS (
                SELECT user_id,
                       array_agg(DISTINCT device_id::text) FILTER (WHERE device_id IS NOT NULL) AS device_ids
                  FROM (
                      SELECT user_id, device_id FROM public.device_owners
                      UNION ALL
                      SELECT user_id, device_id FROM public.device_members
                  ) linked
                 GROUP BY user_id
            )
            SELECT u.id, u.name, u.email,
                   COALESCE(c.national_ids, ARRAY[]::text[]) AS national_ids,
                   COALESCE(d.device_ids, ARRAY[]::text[]) AS device_ids
              FROM public.users u
              LEFT JOIN cattle_ids c ON c.user_id=u.id
              LEFT JOIN linked_devices d ON d.user_id=u.id
             WHERE c.user_id IS NOT NULL OR d.user_id IS NOT NULL
             ORDER BY COALESCE(u.name, u.email, u.id::text), u.id
            """
        ).fetchall()
    return {"users": [dict(row) for row in rows]}


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


@router.delete("/users/{user_id}")
def revoke_admin(user_id: int, admin=Depends(require_admin)):
    if admin["provider"] != "admin":
        raise HTTPException(403, "최고 관리자만 다른 관리자의 권한을 해제할 수 있습니다.")
    if user_id == admin["id"]:
        raise HTTPException(400, "자기 자신의 관리자 권한은 해제할 수 없습니다.")
    database_url = os.getenv("DATABASE_URL")
    with psycopg.connect(database_url) as connection:
        target = connection.execute(
            "SELECT provider FROM public.users WHERE id=%s LIMIT 1", (user_id,)
        ).fetchone()
        if target and target[0] == "admin":
            raise HTTPException(400, "최고 관리자 계정은 해제할 수 없습니다.")
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

"""관리자 알림 API."""
import os

import psycopg
from fastapi import APIRouter, Depends, Query

from admin_auth import require_admin

router = APIRouter(prefix="/admin/notifications", tags=["Admin notifications"])


def _database_url():
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL이 설정되지 않았습니다.")
    return value


@router.get("")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    admin=Depends(require_admin),
):
    with psycopg.connect(_database_url()) as connection:
        rows = connection.execute(
            """SELECT id, event_type, title, message, severity,
                      related_segment_id, is_read, created_at, read_at
               FROM public.admin_notifications
               WHERE (%s = FALSE OR is_read = FALSE)
               ORDER BY created_at DESC
               LIMIT %s""",
            (unread_only, limit),
        ).fetchall()
        unread_count = connection.execute(
            "SELECT count(*) FROM public.admin_notifications WHERE is_read = FALSE"
        ).fetchone()[0]
    return {
        "unread_count": unread_count,
        "notifications": [
            {
                "id": row[0],
                "event_type": row[1],
                "title": row[2],
                "message": row[3],
                "severity": row[4],
                "related_segment_id": row[5],
                "is_read": row[6],
                "created_at": row[7],
                "read_at": row[8],
            }
            for row in rows
        ],
    }


@router.post("/{notification_id}/read")
def mark_notification_read(notification_id: int, admin=Depends(require_admin)):
    with psycopg.connect(_database_url()) as connection:
        updated = connection.execute(
            """UPDATE public.admin_notifications
               SET is_read = TRUE, read_at = now()
               WHERE id = %s""",
            (notification_id,),
        ).rowcount
        connection.commit()
    return {"notification_id": notification_id, "is_read": bool(updated)}


@router.post("/read-all")
def mark_all_notifications_read(admin=Depends(require_admin)):
    with psycopg.connect(_database_url()) as connection:
        updated = connection.execute(
            """UPDATE public.admin_notifications
               SET is_read = TRUE, read_at = now()
               WHERE is_read = FALSE"""
        ).rowcount
        connection.commit()
    return {"updated": updated}

"""관리자 알림 저장소 공통 함수."""
import os

import psycopg


def _database_url():
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL이 설정되지 않았습니다.")
    return value


def create_admin_notification(
    event_type: str,
    title: str,
    message: str,
    severity: str = "info",
    related_segment_id: int | None = None,
    event_key: str | None = None,
):
    """중복 키가 있으면 기존 알림을 재사용하고, 없으면 새 알림을 만든다."""
    with psycopg.connect(_database_url()) as connection:
        row = connection.execute(
            """INSERT INTO public.admin_notifications
               (event_type, title, message, severity, related_segment_id, event_key)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (event_key) DO UPDATE SET
                   title = EXCLUDED.title,
                   message = EXCLUDED.message,
                   severity = EXCLUDED.severity
               RETURNING id""",
            (event_type, title, message, severity, related_segment_id, event_key),
        ).fetchone()
        connection.commit()
    return row[0]

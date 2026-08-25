"""Verified, user-selected email address for scheduled COWOW reports."""
import hashlib
import os
import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from auth_session import read_user_id
from device_claim_api import get_connection


router = APIRouter(prefix="/api/reports/recipient", tags=["Report recipient"])


class RecipientEmailRequest(BaseModel):
    email: str


class VerificationRequest(BaseModel):
    code: str


def user_id_from_session(token):
    return read_user_id(token)


def ensure_schema(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_report_recipients (
                user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                email TEXT,
                pending_email TEXT,
                code_hash TEXT,
                code_expires_at TIMESTAMPTZ,
                verified_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    connection.commit()


def hash_code(code):
    return hashlib.sha256(code.encode()).hexdigest()


def send_code(email, code):
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    if not username or not password:
        raise HTTPException(500, "메일 발송 계정이 설정되지 않았습니다.")
    message = EmailMessage()
    message["Subject"] = "[COWOW] 보고서 수신 이메일 인증 코드"
    message["From"] = f"{os.getenv('SMTP_FROM_NAME', 'COWOW')} <{username}>"
    message["To"] = email
    message.set_content(f"COWOW 보고서 수신 이메일 인증 코드: {code}\n이 코드는 10분 동안 유효합니다.")
    try:
        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587")), timeout=20) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
    except Exception as exc:
        raise HTTPException(502, "인증 메일 발송에 실패했습니다.") from exc


@router.get("")
def get_recipient(cowow_session: str | None = Cookie(default=None)):
    user_id = user_id_from_session(cowow_session)
    with get_connection() as connection:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT email FROM users WHERE id=%s", (user_id,))
            user = cursor.fetchone()
            cursor.execute("SELECT email, pending_email, verified_at FROM user_report_recipients WHERE user_id=%s", (user_id,))
            row = cursor.fetchone()
    return {
        "loginEmail": user[0] if user else None,
        "recipientEmail": row[0] if row and row[2] else None,
        "pendingEmail": row[1] if row else None,
    }


@router.post("/send-code")
def send_recipient_code(body: RecipientEmailRequest, cowow_session: str | None = Cookie(default=None)):
    user_id = user_id_from_session(cowow_session)
    email = str(body.email).strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or len(email) > 320:
        raise HTTPException(400, "올바른 이메일 주소를 입력해 주세요.")
    code = f"{secrets.randbelow(1000000):06d}"
    with get_connection() as connection:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO user_report_recipients(user_id, pending_email, code_hash, code_expires_at, updated_at)
                   VALUES (%s,%s,%s,NOW() + INTERVAL '10 minutes',NOW())
                   ON CONFLICT(user_id) DO UPDATE SET pending_email=EXCLUDED.pending_email, code_hash=EXCLUDED.code_hash,
                   code_expires_at=EXCLUDED.code_expires_at, updated_at=NOW()""",
                (user_id, email, hash_code(code)),
            )
        connection.commit()
    send_code(email, code)
    return {"message": "인증 코드를 보냈습니다."}


@router.post("/verify")
def verify_recipient_code(body: VerificationRequest, cowow_session: str | None = Cookie(default=None)):
    user_id = user_id_from_session(cowow_session)
    code = body.code.strip()
    with get_connection() as connection:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE user_report_recipients
                   SET email=pending_email, pending_email=NULL, code_hash=NULL, code_expires_at=NULL, verified_at=NOW(), updated_at=NOW()
                   WHERE user_id=%s AND code_hash=%s AND code_expires_at > NOW() AND pending_email IS NOT NULL
                   RETURNING email""",
                (user_id, hash_code(code)),
            )
            row = cursor.fetchone()
        connection.commit()
    if not row:
        raise HTTPException(400, "인증 코드가 올바르지 않거나 만료되었습니다.")
    return {"recipientEmail": row[0], "message": "보고서 수신 이메일이 인증되었습니다."}

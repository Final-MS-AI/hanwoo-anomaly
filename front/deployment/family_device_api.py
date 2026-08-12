import html
import os
import smtplib
from email.message import EmailMessage

import psycopg
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, Field

from device_claim_api import (
    CLAIM_CODE_EXPIRE_MINUTES,
    generate_code,
    get_connection,
    get_user,
    hash_code,
    normalize_code,
    require_user,
)


router = APIRouter(tags=["Family device sharing"])

PHYSICAL_DEVICE_ID = os.getenv("ESP32_PHYSICAL_DEVICE_ID", "ESP32-01")
PUBLIC_DEVICE_NUMBER = os.getenv("ESP32_PUBLIC_DEVICE_NUMBER", "COWOW-0001")


class ShareInviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ShareJoinRequest(BaseModel):
    shareCode: str = Field(min_length=1, max_length=40)


class TransferAdminRequest(BaseModel):
    userId: int


class DisconnectDeviceRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=100)


class ActuatorRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=100)
    actuator: str
    value: int | bool


def normalize_email(value: str):
    return value.strip().lower()


def ensure_schema():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS device_members (
                    device_id TEXT NOT NULL
                        REFERENCES cowow_devices(device_id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (device_id, user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_device_members_one_device
                ON device_members(user_id)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS device_share_codes (
                    id BIGSERIAL PRIMARY KEY,
                    device_id TEXT NOT NULL
                        REFERENCES cowow_devices(device_id) ON DELETE CASCADE,
                    invited_email TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    created_by BIGINT NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    expires_at TIMESTAMPTZ NOT NULL,
                    used_at TIMESTAMPTZ,
                    accepted_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_device_share_codes_lookup
                ON device_share_codes(invited_email, code_hash, used_at, expires_at)
                """
            )
        connection.commit()


def current_user(cowow_session):
    user_id = require_user(cowow_session)
    with get_connection() as connection:
        return get_user(connection, user_id)


def role_for(connection, user_id, device_id=PHYSICAL_DEVICE_ID):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM device_owners WHERE device_id=%s AND user_id=%s",
            (device_id, user_id),
        )
        if cursor.fetchone():
            return "admin"
        cursor.execute(
            "SELECT 1 FROM device_members WHERE device_id=%s AND user_id=%s",
            (device_id, user_id),
        )
        if cursor.fetchone():
            return "member"
    return None


def require_access(connection, user, device_id):
    if device_id != PHYSICAL_DEVICE_ID:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")
    role = role_for(connection, user["id"], device_id)
    if role:
        return role
    if user["provider"] == "guest":
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM device_owners WHERE device_id=%s", (device_id,))
            if not cursor.fetchone():
                return "guest"
    raise HTTPException(status_code=403, detail="이 장비에 접근할 권한이 없습니다.")


def send_share_email(recipient, name, code, admin_name):
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    if not username or not password:
        raise HTTPException(status_code=500, detail="메일 발송 계정이 설정되지 않았습니다.")
    safe_name = html.escape(name or "구성원")
    safe_admin = html.escape(admin_name or "관리자")
    safe_code = html.escape(code)
    message = EmailMessage()
    message["Subject"] = "[COWOW] 가족 장비 공유 인증 코드"
    message["From"] = f"COWOW <{username}>"
    message["To"] = recipient
    message.set_content(
        f"안녕하세요, {name or '구성원'}님.\n\n"
        f"{admin_name or '관리자'}님이 COWOW 장비를 공유했습니다.\n"
        f"공유 인증 코드: {code}\n\n"
        f"이 코드는 {CLAIM_CODE_EXPIRE_MINUTES}분 동안 한 번만 사용할 수 있습니다."
    )
    message.add_alternative(
        f"""<!doctype html><html lang="ko"><body style="margin:0;background:#f3f5f2;font-family:Arial,sans-serif;color:#2f2a25"><table width="100%" cellpadding="0" cellspacing="0" style="padding:28px 12px"><tr><td align="center"><table width="100%" cellpadding="0" cellspacing="0" style="max-width:540px;background:#fff;border:1px solid #dfe8df;border-radius:18px;overflow:hidden"><tr><td style="padding:24px;background:#34784a;color:#fff;text-align:center;font-size:28px;font-weight:900">COWOW</td></tr><tr><td style="padding:30px"><h2 style="margin:0 0 12px">가족 장비 공유 초대</h2><p style="line-height:1.7;color:#6e655d">안녕하세요, <b>{safe_name}</b>님.<br><b>{safe_admin}</b>님이 센서 확인과 장치 제어 권한을 공유했습니다.</p><div style="margin:24px 0;padding:22px;background:#f1f7f2;border:1px solid #c9dfce;border-radius:14px;text-align:center"><div style="font-size:12px;color:#718076">공유 인증 코드</div><div style="margin-top:8px;color:#245f37;font-size:30px;font-weight:900;letter-spacing:4px">{safe_code}</div><div style="margin-top:10px;color:#8a7d71;font-size:12px">{CLAIM_CODE_EXPIRE_MINUTES}분 동안 한 번만 사용 가능</div></div><p style="font-size:13px;line-height:1.8">COWOW 로그인 → 장비 연결 → 가족 공유 참여에서 코드를 입력하세요.</p></td></tr></table></td></tr></table></body></html>""",
        subtype="html",
    )
    try:
        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587")), timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="가족 공유 메일 발송에 실패했습니다.") from exc


@router.get("/devices/sharing")
def sharing_info(cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    with get_connection() as connection:
        role = require_access(connection, user, PHYSICAL_DEVICE_ID)
        if role == "guest":
            raise HTTPException(status_code=403, detail="게스트는 가족 공유를 사용할 수 없습니다.")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id,u.name,u.email,'admin',o.registered_at
                FROM device_owners o JOIN users u ON u.id=o.user_id
                WHERE o.device_id=%s
                UNION ALL
                SELECT u.id,u.name,u.email,'member',m.joined_at
                FROM device_members m JOIN users u ON u.id=m.user_id
                WHERE m.device_id=%s
                ORDER BY 5
                """,
                (PHYSICAL_DEVICE_ID, PHYSICAL_DEVICE_ID),
            )
            rows = cursor.fetchall()
    return {"role": role, "deviceId": PHYSICAL_DEVICE_ID, "members": [
        {"userId": row[0], "name": row[1], "email": row[2], "role": row[3], "joinedAt": row[4].isoformat()}
        for row in rows
    ]}


@router.post("/devices/share-code")
def create_share_code(body: ShareInviteRequest, cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    invited_email = normalize_email(body.email)
    if "@" not in invited_email or invited_email.startswith("@") or invited_email.endswith("@"):
        raise HTTPException(status_code=400, detail="Invalid email address.")
    if user["provider"] == "guest" or not user.get("email"):
        raise HTTPException(status_code=403, detail="이 계정은 장비를 공유할 수 없습니다.")
    if invited_email == normalize_email(user["email"]):
        raise HTTPException(status_code=400, detail="본인 이메일에는 초대할 수 없습니다.")
    with get_connection() as connection:
        if role_for(connection, user["id"]) != "admin":
            raise HTTPException(status_code=403, detail="관리자만 구성원을 초대할 수 있습니다.")
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT 1 FROM device_members m JOIN users u ON u.id=m.user_id
                WHERE m.device_id=%s AND LOWER(u.email)=%s""",
                (PHYSICAL_DEVICE_ID, invited_email),
            )
            if cursor.fetchone():
                raise HTTPException(status_code=409, detail="이미 연결된 구성원입니다.")
            code = generate_code()
            cursor.execute(
                "UPDATE device_share_codes SET used_at=NOW() WHERE device_id=%s AND invited_email=%s AND used_at IS NULL",
                (PHYSICAL_DEVICE_ID, invited_email),
            )
            cursor.execute(
                """INSERT INTO device_share_codes(device_id,invited_email,code_hash,created_by,expires_at)
                VALUES(%s,%s,%s,%s,NOW()+(%s*INTERVAL '1 minute'))""",
                (PHYSICAL_DEVICE_ID, invited_email, hash_code(code), user["id"], CLAIM_CODE_EXPIRE_MINUTES),
            )
        connection.commit()
    send_share_email(invited_email, None, code, user["name"])
    return {"message": f"{invited_email}로 가족 공유 인증 코드를 보냈습니다."}


@router.post("/devices/share/join")
def join_shared_device(body: ShareJoinRequest, cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    if user["provider"] == "guest" or not user.get("email"):
        raise HTTPException(status_code=403, detail="소셜 로그인 계정만 공유에 참여할 수 있습니다.")
    email = normalize_email(user["email"])
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM device_owners WHERE user_id=%s UNION ALL SELECT 1 FROM device_members WHERE user_id=%s LIMIT 1", (user["id"], user["id"]))
            if cursor.fetchone():
                raise HTTPException(status_code=409, detail="이 계정에는 이미 장비가 연결되어 있습니다.")
            cursor.execute(
                """SELECT id,device_id,expires_at>NOW(),attempts FROM device_share_codes
                WHERE invited_email=%s AND code_hash=%s AND used_at IS NULL
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE""",
                (email, hash_code(normalize_code(body.shareCode))),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute("UPDATE device_share_codes SET attempts=attempts+1 WHERE invited_email=%s AND used_at IS NULL AND expires_at>NOW()", (email,))
                connection.commit()
                raise HTTPException(status_code=400, detail="공유 인증 코드가 올바르지 않습니다.")
            code_id, device_id, valid, attempts = row
            if not valid:
                raise HTTPException(status_code=400, detail="공유 인증 코드가 만료되었습니다.")
            if attempts >= 5:
                raise HTTPException(status_code=429, detail="입력 횟수를 초과했습니다.")
            cursor.execute("SELECT 1 FROM device_owners WHERE device_id=%s", (device_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=409, detail="관리자가 장비 연결을 해제했습니다.")
            cursor.execute("INSERT INTO device_members(device_id,user_id) VALUES(%s,%s)", (device_id, user["id"]))
            cursor.execute("UPDATE device_share_codes SET used_at=NOW(),accepted_by=%s WHERE id=%s", (user["id"], code_id))
        connection.commit()
    return {"device": {"deviceId": device_id, "publicDeviceNumber": "shared", "deviceName": "공유된 COWOW ESP32-01", "role": "member", "guest": False}}


@router.delete("/devices/members/{member_user_id}", status_code=204)
def remove_member(member_user_id: int, cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    with get_connection() as connection:
        if role_for(connection, user["id"]) != "admin":
            raise HTTPException(status_code=403, detail="관리자만 구성원을 제거할 수 있습니다.")
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM device_members WHERE device_id=%s AND user_id=%s RETURNING user_id", (PHYSICAL_DEVICE_ID, member_user_id))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="구성원을 찾을 수 없습니다.")
        connection.commit()
    return Response(status_code=204)


@router.post("/devices/admin/transfer")
def transfer_admin(body: TransferAdminRequest, cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id,barn_name FROM device_owners WHERE device_id=%s FOR UPDATE", (PHYSICAL_DEVICE_ID,))
            owner = cursor.fetchone()
            if not owner or owner[0] != user["id"]:
                raise HTTPException(status_code=403, detail="현재 관리자만 권한을 이전할 수 있습니다.")
            cursor.execute("DELETE FROM device_members WHERE device_id=%s AND user_id=%s RETURNING joined_at", (PHYSICAL_DEVICE_ID, body.userId))
            target = cursor.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="임명할 구성원을 찾을 수 없습니다.")
            cursor.execute("UPDATE device_owners SET user_id=%s,updated_at=NOW() WHERE device_id=%s", (body.userId, PHYSICAL_DEVICE_ID))
            cursor.execute("INSERT INTO device_members(device_id,user_id,joined_at) VALUES(%s,%s,NOW())", (PHYSICAL_DEVICE_ID, user["id"]))
        connection.commit()
    return {"message": "관리자 권한을 이전했습니다."}


@router.get("/devices/mine")
def my_devices(cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    with get_connection() as connection:
        role = role_for(connection, user["id"])
        if not role and user["provider"] == "guest":
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM device_owners WHERE device_id=%s", (PHYSICAL_DEVICE_ID,))
                if not cursor.fetchone():
                    role = "guest"
        if not role:
            return {"devices": []}
        with connection.cursor() as cursor:
            cursor.execute("SELECT last_seen_at,last_seen_at>NOW()-INTERVAL '30 seconds' FROM device_status WHERE device_id=%s", (PHYSICAL_DEVICE_ID,))
            status = cursor.fetchone()
    return {"devices": [{"deviceId": PHYSICAL_DEVICE_ID, "publicDeviceNumber": "guest" if role == "guest" else PUBLIC_DEVICE_NUMBER, "deviceName": "COWOW ESP32-01", "role": role, "guest": role == "guest", "lastSeenAt": status[0].isoformat() if status and status[0] else None, "online": bool(status and status[1])}]}


@router.delete("/devices/connection", status_code=204)
def disconnect(body: DisconnectDeviceRequest, cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    with get_connection() as connection:
        role = role_for(connection, user["id"], body.deviceId)
        if user["provider"] == "guest" or not role:
            return Response(status_code=204)
        with connection.cursor() as cursor:
            if role == "member":
                cursor.execute("DELETE FROM device_members WHERE device_id=%s AND user_id=%s", (body.deviceId, user["id"]))
            else:
                cursor.execute("SELECT user_id FROM device_members WHERE device_id=%s ORDER BY joined_at LIMIT 1 FOR UPDATE", (body.deviceId,))
                successor = cursor.fetchone()
                if successor:
                    cursor.execute("DELETE FROM device_members WHERE device_id=%s AND user_id=%s", (body.deviceId, successor[0]))
                    cursor.execute("UPDATE device_owners SET user_id=%s,updated_at=NOW() WHERE device_id=%s", (successor[0], body.deviceId))
                else:
                    cursor.execute("DELETE FROM device_owners WHERE device_id=%s AND user_id=%s", (body.deviceId, user["id"]))
                    cursor.execute("UPDATE device_share_codes SET used_at=NOW() WHERE device_id=%s AND used_at IS NULL", (body.deviceId,))
        connection.commit()
    return Response(status_code=204)


@router.post("/actuators")
def actuator(body: ActuatorRequest, cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    if body.actuator not in {"ventilation_fan", "water_sprayer"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 장치입니다.")
    with get_connection() as connection:
        require_access(connection, user, body.deviceId)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE device_commands SET status='superseded' WHERE device_id=%s AND actuator=%s AND status='pending'", (body.deviceId, body.actuator))
            cursor.execute(
                "INSERT INTO device_commands(device_id,user_id,actuator,command_value,status) VALUES(%s,%s,%s,%s,'pending') RETURNING id",
                (body.deviceId, user["id"], body.actuator, Jsonb(int(body.value))),
            )
            command_id = cursor.fetchone()[0]
        connection.commit()
    return {"commandId": command_id, "status": "pending"}


@router.get("/devices/{device_id}/state")
def device_state(device_id: str, cowow_session: str | None = Cookie(default=None)):
    user = current_user(cowow_session)
    with get_connection() as connection:
        require_access(connection, user, device_id)
        with connection.cursor() as cursor:
            cursor.execute("""SELECT firmware_version,wifi_rssi,last_seen_at,temperature,humidity,ammonia,carbon_dioxide,telemetry_at,last_seen_at>NOW()-INTERVAL '30 seconds' FROM device_status WHERE device_id=%s""", (device_id,))
            row = cursor.fetchone()
    if not row:
        return {"deviceId": device_id, "online": False, "lastSeenAt": None, "sensors": {}}
    return {"deviceId": device_id, "firmwareVersion": row[0], "wifiRssi": row[1], "lastSeenAt": row[2].isoformat() if row[2] else None, "telemetryAt": row[7].isoformat() if row[7] else None, "online": bool(row[8]), "sensors": {"temperature": row[3], "humidity": row[4], "airQuality": row[5]}}

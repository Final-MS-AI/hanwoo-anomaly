import hashlib
import os
import secrets
import smtplib
import string
from email.message import EmailMessage

import psycopg
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from auth_session import read_user_id


router = APIRouter(tags=["Device registration"])

DATABASE_URL = os.getenv("DATABASE_URL", "")
DEMO_DEVICE_ID = os.getenv("ESP32_DEMO_DEVICE_ID", "ESP32-DEMO-01")
CLAIM_CODE_SECRET = os.getenv("CLAIM_CODE_SECRET", "")
CLAIM_CODE_EXPIRE_MINUTES = int(
    os.getenv("CLAIM_CODE_EXPIRE_MINUTES", "10")
)


class ClaimDeviceRequest(BaseModel):
    claimCode: str = Field(min_length=1, max_length=40)
    barnName: str = Field(default="1번 축사", max_length=100)


def get_connection():
    if not DATABASE_URL:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL이 설정되지 않았습니다.",
        )
    return psycopg.connect(DATABASE_URL)


def require_user(cowow_session: str | None):
    if not cowow_session:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
        )

    try:
        user_id = read_user_id(cowow_session)
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail="로그인 세션이 만료되었습니다.",
        ) from exc

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
        )

    return user_id


def get_user(connection, user_id):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, provider, name, email
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()

    if not row:
        raise HTTPException(
            status_code=401,
            detail="사용자 정보를 찾을 수 없습니다.",
        )

    return {
        "id": row[0],
        "provider": row[1],
        "name": row[2],
        "email": row[3],
    }


def normalize_code(value: str):
    return value.strip().upper().replace(" ", "")


def hash_code(value: str):
    if not CLAIM_CODE_SECRET:
        raise HTTPException(
            status_code=500,
            detail="CLAIM_CODE_SECRET이 설정되지 않았습니다.",
        )

    normalized = normalize_code(value)
    source = f"{CLAIM_CODE_SECRET}:{normalized}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def generate_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def mask_email(email: str):
    local, separator, domain = email.partition("@")
    if not separator:
        return email

    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def send_claim_email(
    email: str,
    name: str | None,
    code: str,
):
    import html

    smtp_host = os.getenv(
        "SMTP_HOST",
        "smtp.gmail.com",
    )
    smtp_port = int(
        os.getenv("SMTP_PORT", "587")
    )
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from_name = os.getenv(
        "SMTP_FROM_NAME",
        "COWOW",
    )

    if not smtp_username or not smtp_password:
        raise HTTPException(
            status_code=500,
            detail="메일 발송 계정이 설정되지 않았습니다.",
        )

    safe_name = html.escape(name or "사용자")
    safe_code = html.escape(code)
    safe_email = html.escape(email)

    message = EmailMessage()
    message["Subject"] = "[COWOW] 장비 일회용 등록 코드"
    message["From"] = (
        f"{smtp_from_name} <{smtp_username}>"
    )
    message["To"] = email

    message.set_content(
        f"""안녕하세요, {name or '사용자'}님.

COWOW 축사 환경관리 장비 등록 코드입니다.

등록 코드: {code}

이 코드는 {CLAIM_CODE_EXPIRE_MINUTES}분 동안 유효하며,
한 번 사용하면 자동으로 폐기됩니다.

등록 방법
1. COWOW 웹에서 장비 연결 화면을 엽니다.
2. 위 등록 코드를 입력합니다.
3. 설치할 축사를 확인합니다.
4. 장비 연결하고 제어 시작 버튼을 누릅니다.

본인이 요청하지 않은 메일이라면 코드를 사용하지 말고
이 메일을 삭제해 주세요.

COWOW
스마트 한우 축사 환경관리 서비스
"""
    )

    message.add_alternative(
        f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
  >
</head>
<body style="
  margin:0;
  padding:0;
  background:#f3f5f2;
  font-family:Arial,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
  color:#2f2a25;
">
  <table
    role="presentation"
    width="100%"
    cellspacing="0"
    cellpadding="0"
    style="background:#f3f5f2;padding:28px 12px;"
  >
    <tr>
      <td align="center">
        <table
          role="presentation"
          width="100%"
          cellspacing="0"
          cellpadding="0"
          style="
            max-width:560px;
            overflow:hidden;
            background:#ffffff;
            border:1px solid #dfe8df;
            border-radius:20px;
          "
        >
          <tr>
            <td style="
              padding:26px 28px;
              background:#34784a;
              text-align:center;
            ">
              <div style="
                color:#ffffff;
                font-size:30px;
                font-weight:900;
                letter-spacing:1px;
              ">
                COWOW
              </div>
              <div style="
                margin-top:6px;
                color:#dcefe1;
                font-size:13px;
              ">
                스마트 한우 축사 환경관리
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:32px 28px;">
              <div style="
                margin-bottom:10px;
                color:#34784a;
                font-size:13px;
                font-weight:700;
              ">
                장비 등록 요청
              </div>

              <h1 style="
                margin:0 0 12px;
                color:#29231e;
                font-size:23px;
                line-height:1.4;
              ">
                장비 등록 코드를 확인해 주세요
              </h1>

              <p style="
                margin:0;
                color:#6e655d;
                font-size:15px;
                line-height:1.7;
              ">
                안녕하세요, <strong>{safe_name}</strong>님.<br>
                아래 코드를 COWOW 장비 연결 화면에 입력해 주세요.
              </p>

              <div style="
                margin:26px 0;
                padding:24px 16px;
                background:#f1f7f2;
                border:1px solid #c9dfce;
                border-radius:16px;
                text-align:center;
              ">
                <div style="
                  margin-bottom:9px;
                  color:#718076;
                  font-size:12px;
                  font-weight:700;
                ">
                  일회용 등록 코드
                </div>

                <div style="
                  color:#245f37;
                  font-size:32px;
                  font-weight:900;
                  letter-spacing:4px;
                ">
                  {safe_code}
                </div>

                <div style="
                  margin-top:12px;
                  color:#8a7d71;
                  font-size:12px;
                ">
                  발급 후 {CLAIM_CODE_EXPIRE_MINUTES}분 동안 유효합니다
                </div>
              </div>

              <div style="
                padding:18px;
                background:#faf9f6;
                border-radius:14px;
              ">
                <div style="
                  margin-bottom:12px;
                  color:#443b33;
                  font-size:14px;
                  font-weight:800;
                ">
                  장비 연결 방법
                </div>

                <ol style="
                  margin:0;
                  padding-left:21px;
                  color:#665d55;
                  font-size:13px;
                  line-height:1.9;
                ">
                  <li>COWOW 장비 연결 화면을 엽니다.</li>
                  <li>위 일회용 등록 코드를 입력합니다.</li>
                  <li>장비를 설치할 축사를 확인합니다.</li>
                  <li>장비 연결하고 제어 시작을 누릅니다.</li>
                </ol>
              </div>

              <p style="
                margin:20px 0 0;
                color:#9a5148;
                font-size:12px;
                line-height:1.7;
              ">
                이 코드는 한 번만 사용할 수 있습니다.
                본인이 요청하지 않았다면 코드를 입력하지 마세요.
              </p>
            </td>
          </tr>

          <tr>
            <td style="
              padding:20px 28px;
              background:#f8faf8;
              border-top:1px solid #e5ebe5;
              color:#8b8178;
              font-size:11px;
              line-height:1.6;
              text-align:center;
            ">
              이 메일은 {safe_email} 계정의 장비 등록 요청으로
              자동 발송되었습니다.<br>
              © COWOW Smart Livestock Management
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
""",
        subtype="html",
    )

    try:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=20,
        ) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(
                smtp_username,
                smtp_password,
            )
            smtp.send_message(message)

    except Exception as exc:
        print(
            "등록 코드 메일 발송 오류:",
            repr(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="등록 코드 메일 발송에 실패했습니다.",
        ) from exc


def ensure_schema():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cowow_devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS device_owners (
                    device_id TEXT PRIMARY KEY
                        REFERENCES cowow_devices(device_id)
                        ON DELETE CASCADE,
                    user_id BIGINT NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    barn_name TEXT NOT NULL DEFAULT '1번 축사',
                    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_device_owners_user_id
                ON device_owners(user_id)
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS device_claim_codes (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    device_id TEXT NOT NULL
                        REFERENCES cowow_devices(device_id)
                        ON DELETE CASCADE,
                    code_hash TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    expires_at TIMESTAMPTZ NOT NULL,
                    used_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_device_claim_codes_lookup
                ON device_claim_codes(
                    user_id,
                    code_hash,
                    used_at,
                    expires_at
                )
                """
            )

            cursor.execute(
                """
                INSERT INTO cowow_devices (
                    device_id,
                    device_name
                )
                VALUES (%s, %s)
                ON CONFLICT (device_id)
                DO UPDATE SET
                    device_name = EXCLUDED.device_name,
                    is_active = TRUE
                """,
                (
                    DEMO_DEVICE_ID,
                    f"ESP32 {DEMO_DEVICE_ID}",
                ),
            )

        connection.commit()


@router.post("/devices/claim-code/send-legacy")
def send_device_claim_code(
    cowow_session: str | None = Cookie(default=None),
):
    user_id = require_user(cowow_session)

    with get_connection() as connection:
        user = get_user(connection, user_id)

        if user["provider"] == "guest":
            raise HTTPException(
                status_code=400,
                detail="게스트는 등록 코드 guest를 사용해 주세요.",
            )

        if not user["email"]:
            raise HTTPException(
                status_code=400,
                detail="로그인 계정에 이메일 정보가 없습니다.",
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.device_id
                FROM cowow_devices d
                LEFT JOIN device_owners owner
                    ON owner.device_id = d.device_id
                WHERE d.is_active = TRUE
                  AND (
                      owner.user_id IS NULL
                      OR owner.user_id = %s
                  )
                ORDER BY
                    CASE WHEN d.device_id = %s THEN 0 ELSE 1 END,
                    d.created_at
                LIMIT 1
                """,
                (user_id, DEMO_DEVICE_ID),
            )
            device_row = cursor.fetchone()

            if not device_row:
                raise HTTPException(
                    status_code=409,
                    detail="현재 등록 가능한 장비가 없습니다.",
                )

            device_id = device_row[0]
            code = generate_code()

            cursor.execute(
                """
                UPDATE device_claim_codes
                SET used_at = NOW()
                WHERE user_id = %s
                  AND used_at IS NULL
                """,
                (user_id,),
            )

            cursor.execute(
                """
                INSERT INTO device_claim_codes (
                    user_id,
                    device_id,
                    code_hash,
                    expires_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    NOW() + (%s * INTERVAL '1 minute')
                )
                """,
                (
                    user_id,
                    device_id,
                    hash_code(code),
                    CLAIM_CODE_EXPIRE_MINUTES,
                ),
            )

        connection.commit()

    send_claim_email(
        user["email"],
        user["name"],
        code,
    )

    return {
        "message": (
            f"{mask_email(user['email'])}로 등록 코드를 보냈습니다. "
            f"{CLAIM_CODE_EXPIRE_MINUTES}분 안에 입력해 주세요."
        ),
        "expiresInMinutes": CLAIM_CODE_EXPIRE_MINUTES,
    }


@router.post("/devices/claim-legacy-v2")
def claim_device(
    body: ClaimDeviceRequest,
    cowow_session: str | None = Cookie(default=None),
):
    user_id = require_user(cowow_session)
    normalized_code = normalize_code(body.claimCode)

    with get_connection() as connection:
        user = get_user(connection, user_id)

        if user["provider"] == "guest":
            if normalized_code != "GUEST":
                raise HTTPException(
                    status_code=400,
                    detail="게스트 등록 코드는 guest입니다.",
                )

            return {
                "device": {
                    "deviceId": DEMO_DEVICE_ID,
                    "deviceName": f"ESP32 {DEMO_DEVICE_ID}",
                    "barnName": body.barnName or "게스트 데모 축사",
                    "guest": True,
                }
            }

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    device_id,
                    expires_at > NOW() AS valid_time,
                    attempts
                FROM device_claim_codes
                WHERE user_id = %s
                  AND code_hash = %s
                  AND used_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, hash_code(normalized_code)),
            )
            claim_row = cursor.fetchone()

            if not claim_row:
                cursor.execute(
                    """
                    UPDATE device_claim_codes
                    SET attempts = attempts + 1
                    WHERE user_id = %s
                      AND used_at IS NULL
                      AND expires_at > NOW()
                    """,
                    (user_id,),
                )
                connection.commit()

                raise HTTPException(
                    status_code=400,
                    detail="등록 코드가 올바르지 않습니다.",
                )

            claim_id, device_id, valid_time, attempts = claim_row

            if not valid_time:
                raise HTTPException(
                    status_code=400,
                    detail="등록 코드가 만료되었습니다. 새 코드를 받아 주세요.",
                )

            if attempts >= 5:
                raise HTTPException(
                    status_code=429,
                    detail="입력 횟수를 초과했습니다. 새 코드를 받아 주세요.",
                )

            cursor.execute(
                """
                SELECT user_id
                FROM device_owners
                WHERE device_id = %s
                FOR UPDATE
                """,
                (device_id,),
            )
            owner_row = cursor.fetchone()

            if owner_row and owner_row[0] != user_id:
                raise HTTPException(
                    status_code=409,
                    detail="이미 다른 계정에 등록된 장비입니다.",
                )

            cursor.execute(
                """
                INSERT INTO device_owners (
                    device_id,
                    user_id,
                    barn_name
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (device_id)
                DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    barn_name = EXCLUDED.barn_name,
                    updated_at = NOW()
                WHERE device_owners.user_id = EXCLUDED.user_id
                """,
                (
                    device_id,
                    user_id,
                    body.barnName or "1번 축사",
                ),
            )

            cursor.execute(
                """
                UPDATE device_claim_codes
                SET used_at = NOW()
                WHERE id = %s
                """,
                (claim_id,),
            )

            cursor.execute(
                """
                SELECT device_name
                FROM cowow_devices
                WHERE device_id = %s
                """,
                (device_id,),
            )
            device_name = cursor.fetchone()[0]

        connection.commit()

    return {
        "device": {
            "deviceId": device_id,
            "deviceName": device_name,
            "barnName": body.barnName or "1번 축사",
            "guest": False,
        }
    }


@router.get("/devices/mine-legacy")
def get_my_devices(
    cowow_session: str | None = Cookie(default=None),
):
    user_id = require_user(cowow_session)

    with get_connection() as connection:
        user = get_user(connection, user_id)

        if user["provider"] == "guest":
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        last_seen_at,
                        COALESCE(
                            last_seen_at > NOW() - INTERVAL '30 seconds',
                            FALSE
                        )
                    FROM device_status
                    WHERE device_id = %s
                    """,
                    (DEMO_DEVICE_ID,),
                )
                status_row = cursor.fetchone()

            return {
                "devices": [{
                    "deviceId": DEMO_DEVICE_ID,
                    "deviceName": f"ESP32 {DEMO_DEVICE_ID}",
                    "barnName": "게스트 데모 축사",
                    "lastSeenAt": (
                        status_row[0].isoformat()
                        if status_row and status_row[0]
                        else None
                    ),
                    "online": bool(status_row and status_row[1]),
                    "guest": True,
                }]
            }

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    d.device_id,
                    d.device_name,
                    owner.barn_name,
                    status.last_seen_at,
                    COALESCE(
                        status.last_seen_at >
                            NOW() - INTERVAL '30 seconds',
                        FALSE
                    )
                FROM device_owners owner
                JOIN cowow_devices d
                    ON d.device_id = owner.device_id
                LEFT JOIN device_status status
                    ON status.device_id = d.device_id
                WHERE owner.user_id = %s
                ORDER BY owner.registered_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

    return {
        "devices": [
            {
                "deviceId": row[0],
                "deviceName": row[1],
                "barnName": row[2],
                "lastSeenAt": (
                    row[3].isoformat()
                    if row[3]
                    else None
                ),
                "online": bool(row[4]),
                "guest": False,
            }
            for row in rows
        ]
    }

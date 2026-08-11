import hashlib
import os
import secrets

import psycopg
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel

from auth_session import create_session_cookie


router = APIRouter(prefix="/auth", tags=["Authentication"])


class GoogleLoginRequest(BaseModel):
    credential: str


@router.post("/google")
def google_login(body: GoogleLoginRequest):
    database_url = os.getenv("DATABASE_URL")
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")

    if not database_url:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL이 설정되지 않았습니다.",
        )

    if not google_client_id:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_CLIENT_ID가 설정되지 않았습니다.",
        )

    try:
        payload = id_token.verify_oauth2_token(
            body.credential,
            google_requests.Request(),
            google_client_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 Google 로그인 토큰입니다.",
        ) from exc

    provider_user_id = payload.get("sub")

    if not provider_user_id:
        raise HTTPException(
            status_code=400,
            detail="Google 사용자 ID가 없습니다.",
        )

    if payload.get("email_verified") is not True:
        raise HTTPException(
            status_code=401,
            detail="인증되지 않은 Google 이메일입니다.",
        )

    name = payload.get("name")
    email = payload.get("email")
    profile_image_url = payload.get("picture")

    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        provider,
                        provider_user_id,
                        name,
                        email,
                        profile_image_url
                    )
                    VALUES ('google', %s, %s, %s, %s)
                    ON CONFLICT (provider, provider_user_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        email = EXCLUDED.email,
                        profile_image_url = EXCLUDED.profile_image_url,
                        updated_at = NOW()
                    RETURNING
                        id,
                        provider,
                        provider_user_id,
                        name,
                        email,
                        profile_image_url
                    """,
                    (
                        provider_user_id,
                        name,
                        email,
                        profile_image_url,
                    ),
                )

                row = cursor.fetchone()

            connection.commit()

    except psycopg.Error as exc:
        print("Google 사용자 저장 오류:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail="Google 사용자 DB 저장에 실패했습니다.",
        ) from exc

    user = {
        "id": row[0],
        "provider": row[1],
        "provider_user_id": row[2],
        "name": row[3],
        "email": row[4],
        "profile_image_url": row[5],
    }

    response = JSONResponse(content=user)
    create_session_cookie(response, row[0])
    return response

@router.post("/google/native")
def google_native_login(body: GoogleLoginRequest):
    database_url = os.getenv("DATABASE_URL")
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")

    if not database_url:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL이 설정되지 않았습니다.",
        )

    if not google_client_id:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_CLIENT_ID가 설정되지 않았습니다.",
        )

    # 기존 웹 Google 로그인과 동일한 방식으로 ID Token을 검증한다.
    try:
        payload = id_token.verify_oauth2_token(
            body.credential,
            google_requests.Request(),
            google_client_id,
        )
    except ValueError as exc:
        # credential 원문은 로그에 출력하지 않는다.
        print(
            "네이티브 Google 토큰 검증 실패:",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 Google 로그인 토큰입니다.",
        ) from exc

    provider_user_id = payload.get("sub")

    if not provider_user_id:
        raise HTTPException(
            status_code=400,
            detail="Google 사용자 ID가 없습니다.",
        )

    if payload.get("email_verified") is not True:
        raise HTTPException(
            status_code=401,
            detail="인증되지 않은 Google 이메일입니다.",
        )

    name = payload.get("name")
    email = payload.get("email")
    profile_image_url = payload.get("picture")

    # 앱에 반환할 일회용 티켓 원문
    raw_ticket = secrets.token_urlsafe(32)

    # DB에는 티켓 원문이 아닌 SHA-256 해시만 저장한다.
    ticket_hash = hashlib.sha256(
        raw_ticket.encode("utf-8")
    ).hexdigest()

    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                # 기존 웹 로그인과 같은 users 테이블을 사용한다.
                cursor.execute(
                    """
                    INSERT INTO users (
                        provider,
                        provider_user_id,
                        name,
                        email,
                        profile_image_url
                    )
                    VALUES ('google', %s, %s, %s, %s)
                    ON CONFLICT (provider, provider_user_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        email = EXCLUDED.email,
                        profile_image_url = EXCLUDED.profile_image_url,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        provider_user_id,
                        name,
                        email,
                        profile_image_url,
                    ),
                )

                user_row = cursor.fetchone()

                if user_row is None:
                    raise RuntimeError(
                        "Google 사용자 ID를 반환받지 못했습니다."
                    )

                user_id = int(user_row[0])

                # 사용자 저장과 티켓 생성을 같은 트랜잭션에서 처리한다.
                cursor.execute(
                    """
                    INSERT INTO public.native_login_tickets (
                        ticket_hash,
                        user_id,
                        expires_at
                    )
                    VALUES (
                        %s,
                        %s,
                        NOW() + INTERVAL '60 seconds'
                    )
                    """,
                    (
                        ticket_hash,
                        user_id,
                    ),
                )

            connection.commit()

    except (psycopg.Error, RuntimeError) as exc:
        # DB 주소, 토큰, 티켓 원문은 로그에 출력하지 않는다.
        print(
            "네이티브 Google 로그인 DB 처리 실패:",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Google 로그인 처리 중 오류가 발생했습니다.",
        ) from exc

    response = JSONResponse(
        content={
            "ticket": raw_ticket,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def create_native_redirect(location: str) -> RedirectResponse:
    response = RedirectResponse(
        url=location,
        status_code=302,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/native/complete")
def complete_native_login(ticket: str):
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL이 설정되지 않았습니다.",
        )

    # 비정상적으로 짧거나 긴 값은 DB 조회 전에 거부한다.
    if len(ticket) < 20 or len(ticket) > 200:
        return create_native_redirect("/login")

    ticket_hash = hashlib.sha256(
        ticket.encode("utf-8")
    ).hexdigest()

    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                # SELECT 후 UPDATE를 따로 하지 않고,
                # 한 번의 UPDATE로 유효성 검사와 소비를 동시에 처리한다.
                cursor.execute(
                    """
                    UPDATE public.native_login_tickets
                    SET consumed_at = NOW()
                    WHERE ticket_hash = %s
                      AND consumed_at IS NULL
                      AND expires_at > NOW()
                    RETURNING user_id
                    """,
                    (ticket_hash,),
                )

                ticket_row = cursor.fetchone()

            connection.commit()

    except psycopg.Error as exc:
        print(
            "네이티브 로그인 티켓 소비 실패:",
            type(exc).__name__,
        )
        return create_native_redirect("/login")

    # 위조, 만료, 재사용을 구분해서 외부에 알려주지 않는다.
    if ticket_row is None:
        return create_native_redirect("/login")

    user_id = int(ticket_row[0])

    response = create_native_redirect("/dashboard")
    create_session_cookie(response, user_id)
    return response

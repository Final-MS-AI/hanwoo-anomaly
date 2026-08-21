from family_device_api import router as family_device_router
import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
import psycopg
from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from ocr_api import router as ocr_router
from ocr_result_media_api import router as ocr_media_router
from rag.rag_api import router as rag_router
from device_api import router as device_router
from device_claim_api import router as device_claim_router
from exclusive_device_api import router as exclusive_device_router
from device_disconnect_api import router as device_disconnect_router
from auth_session import create_session_cookie, router as auth_session_router
from feedback_api import router as feedback_router
from dashboard_api import router as dashboard_router
from admin_auth import router as admin_auth_router
from admin_login import router as admin_login_router

# ---------------------------------------------------------
# 환경변수 로딩
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)


# ---------------------------------------------------------
# 환경변수
# ---------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "https://polite-rock-0ee43f000.7.azurestaticapps.net",
)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
NAVER_REDIRECT_URI = os.getenv(
    "NAVER_REDIRECT_URI",
    "https://hanwoo.koreacentral.cloudapp.azure.com/auth/naver/callback",
)


KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI")


# ---------------------------------------------------------
# FastAPI 애플리케이션
# ---------------------------------------------------------

app = FastAPI(
    title="한우 행동 이상 탐지 API",
    description="한우 개체 추적 및 행동 이상 조기경보 시스템",
    version="0.1.0",
)

# ---------------------------------------------------------
# CORS 설정
# ---------------------------------------------------------

app.include_router(family_device_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://polite-rock-0ee43f000.7.azurestaticapps.net",
        FRONTEND_URL.rstrip("/"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Router 등록
# ---------------------------------------------------------

app.include_router(ocr_router)
app.include_router(ocr_media_router)
app.include_router(rag_router)
app.include_router(device_router)
app.include_router(device_claim_router)
app.include_router(exclusive_device_router)
app.include_router(device_disconnect_router)
app.include_router(auth_session_router)
app.include_router(feedback_router)
app.include_router(dashboard_router)
app.include_router(admin_auth_router)
app.include_router(admin_login_router)


# ---------------------------------------------------------
# 기본 API
# ---------------------------------------------------------

@app.get("/")
def root():
    return {
        "message": "FastAPI server is running",
        "project": "Hanwoo Behavior Anomaly Detection",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
    }


# ---------------------------------------------------------
# 환경변수 확인 API
# 실제 비밀값은 반환하지 않고 존재 여부만 확인
# ---------------------------------------------------------

@app.get("/config-check")
def config_check():
    return {
        "env_path": str(ENV_PATH),
        "env_file_exists": ENV_PATH.exists(),
        "database_url_loaded": bool(DATABASE_URL),
        "kakao_rest_api_key_loaded": bool(KAKAO_REST_API_KEY),
        "kakao_client_secret_loaded": bool(KAKAO_CLIENT_SECRET),
        "kakao_redirect_uri": KAKAO_REDIRECT_URI,
        "frontend_url": FRONTEND_URL,
    }


# ---------------------------------------------------------
# DB 연결 테스트
# ---------------------------------------------------------

@app.get("/db-test")
def db_test():
    if not DATABASE_URL:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL 환경변수가 설정되지 않았습니다.",
        )

    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, message, created_at
                    FROM api_test
                    ORDER BY created_at DESC
                    LIMIT 100
                    """
                )

                rows = cursor.fetchall()

        return {
            "success": True,
            "count": len(rows),
            "data": [
                {
                    "id": row[0],
                    "message": row[1],
                    "created_at": (
                        row[2].isoformat()
                        if row[2] is not None
                        else None
                    ),
                }
                for row in rows
            ],
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"DB 조회 실패: {error}",
        ) from error


# ---------------------------------------------------------
# 카카오 환경변수 검사
# ---------------------------------------------------------

def validate_kakao_environment() -> None:
    missing_values = []

    if not KAKAO_REST_API_KEY:
        missing_values.append("KAKAO_REST_API_KEY")

    if not KAKAO_CLIENT_SECRET:
        missing_values.append("KAKAO_CLIENT_SECRET")

    if not KAKAO_REDIRECT_URI:
        missing_values.append("KAKAO_REDIRECT_URI")

    if not FRONTEND_URL:
        missing_values.append("FRONTEND_URL")

    if missing_values:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "카카오 로그인 환경변수가 누락되었습니다.",
                "missing": missing_values,
                "env_path": str(ENV_PATH),
            },
        )


# ---------------------------------------------------------
# 카카오 로그인 시작
# ---------------------------------------------------------

@app.get("/auth/kakao/login")
def kakao_login():
    validate_kakao_environment()

    state = secrets.token_urlsafe(32)

    authorization_params = {
        "client_id": KAKAO_REST_API_KEY,
        "redirect_uri": KAKAO_REDIRECT_URI,
        "response_type": "code",
        "state": state,
    }

    authorization_url = (
        "https://kauth.kakao.com/oauth/authorize?"
        f"{urlencode(authorization_params)}"
    )

    response = RedirectResponse(
        url=authorization_url,
        status_code=302,
    )

    response.set_cookie(
        key="kakao_oauth_state",
        value=state,
        httponly=True,
        secure=True,  # 현재 FastAPI 주소가 HTTP이므로 False
        samesite="lax",
        max_age=600,
        path="/",
    )

    return response


# ---------------------------------------------------------
# 카카오 로그인 콜백
# ---------------------------------------------------------


@app.get("/auth/naver/login")
async def naver_login():
    if not NAVER_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="NAVER_CLIENT_ID가 설정되지 않았습니다.",
        )

    if not NAVER_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="NAVER_CLIENT_SECRET이 설정되지 않았습니다.",
        )

    state = secrets.token_urlsafe(32)

    authorization_params = {
        "response_type": "code",
        "client_id": NAVER_CLIENT_ID,
        "redirect_uri": NAVER_REDIRECT_URI,
        "state": state,
    }

    authorization_url = (
        "https://nid.naver.com/oauth2.0/authorize?"
        + urlencode(authorization_params)
    )

    response = RedirectResponse(
        url=authorization_url,
        status_code=302,
    )

    response.set_cookie(
        key="naver_oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )

    return response


@app.get("/auth/naver/callback")
async def naver_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    naver_oauth_state: str | None = Cookie(default=None),
):
    if error:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "네이버 로그인 동의 과정에서 오류가 발생했습니다.",
                "error": error,
                "error_description": error_description,
            },
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail="네이버 인가 코드가 없습니다.",
        )

    if not state:
        raise HTTPException(
            status_code=400,
            detail="네이버 OAuth state 값이 없습니다.",
        )

    if not naver_oauth_state:
        raise HTTPException(
            status_code=400,
            detail="네이버 OAuth state 쿠키가 없습니다.",
        )

    if state != naver_oauth_state:
        raise HTTPException(
            status_code=400,
            detail="네이버 OAuth state 검증에 실패했습니다.",
        )

    token_params = {
        "grant_type": "authorization_code",
        "client_id": NAVER_CLIENT_ID,
        "client_secret": NAVER_CLIENT_SECRET,
        "code": code,
        "state": state,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_response = await client.get(
                "https://nid.naver.com/oauth2.0/token",
                params=token_params,
            )

            try:
                token_json = token_response.json()
            except ValueError:
                token_json = {
                    "raw_response": token_response.text,
                }

            if token_response.is_error:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "네이버 액세스 토큰 발급 실패",
                        "status_code": token_response.status_code,
                        "naver_response": token_json,
                    },
                )

            access_token = token_json.get("access_token")

            if not access_token:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": (
                            "네이버 액세스 토큰이 응답에 없습니다."
                        ),
                        "naver_response": token_json,
                    },
                )

            user_response = await client.get(
                "https://openapi.naver.com/v1/nid/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                },
            )

            try:
                user_json = user_response.json()
            except ValueError:
                user_json = {
                    "raw_response": user_response.text,
                }

            if user_response.is_error:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "네이버 사용자 정보 조회 실패",
                        "status_code": user_response.status_code,
                        "naver_response": user_json,
                    },
                )

    except httpx.RequestError as request_error:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "네이버 API 서버 연결에 실패했습니다.",
                "error": str(request_error),
            },
        ) from request_error

    if user_json.get("resultcode") != "00":
        raise HTTPException(
            status_code=400,
            detail={
                "message": "네이버 사용자 정보 응답이 정상적이지 않습니다.",
                "naver_response": user_json,
            },
        )

    profile = user_json.get("response") or {}

    db_user = save_social_user(
        provider="naver",
        provider_user_id=str(profile.get("id") or ""),
        name=(
            profile.get("name")
            or profile.get("nickname")
            or "네이버 사용자"
        ),
        email=profile.get("email"),
        profile_image_url=profile.get("profile_image"),
    )

    user = {
        "provider": "naver",
        "id": db_user["id"],
        "providerUserId": db_user["provider_user_id"],
        "name": (
            profile.get("name")
            or profile.get("nickname")
            or ""
        ),
        "email": profile.get("email") or "",
        "profileImageUrl": (
            profile.get("profile_image")
            or ""
        ),
    }

    frontend_redirect_url = (
        f"{FRONTEND_URL.rstrip('/')}/login?auth=success"
    )

    response = RedirectResponse(
        url=frontend_redirect_url,
        status_code=302,
    )
    create_session_cookie(response, db_user["id"])

    response.delete_cookie(
        key="naver_oauth_state",
        path="/",
    )

    return response


@app.get("/auth/kakao/callback")
async def kakao_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    kakao_oauth_state: str | None = Cookie(default=None),
):
    validate_kakao_environment()

    if error:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "카카오 로그인 동의 과정에서 오류가 발생했습니다.",
                "error": error,
                "error_description": error_description,
            },
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail="카카오 인가 코드가 없습니다.",
        )

    if not state:
        raise HTTPException(
            status_code=400,
            detail="카카오 OAuth state 값이 없습니다.",
        )

    if not kakao_oauth_state:
        raise HTTPException(
            status_code=400,
            detail="카카오 OAuth state 쿠키가 없습니다.",
        )

    if state != kakao_oauth_state:
        raise HTTPException(
            status_code=400,
            detail="카카오 OAuth state 검증에 실패했습니다.",
        )

    token_data = {
        "grant_type": "authorization_code",
        "client_id": KAKAO_REST_API_KEY,
        "client_secret": KAKAO_CLIENT_SECRET,
        "redirect_uri": KAKAO_REDIRECT_URI,
        "code": code,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_response = await client.post(
                "https://kauth.kakao.com/oauth/token",
                data=token_data,
                headers={
                    "Content-Type": (
                        "application/"
                        "x-www-form-urlencoded;charset=utf-8"
                    ),
                },
            )

            try:
                token_json = token_response.json()
            except ValueError:
                token_json = {
                    "raw_response": token_response.text,
                }

            if token_response.is_error:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "카카오 액세스 토큰 발급 실패",
                        "status_code": token_response.status_code,
                        "kakao_response": token_json,
                    },
                )

            access_token = token_json.get("access_token")

            if not access_token:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": (
                            "카카오 액세스 토큰이 응답에 없습니다."
                        ),
                        "kakao_response": token_json,
                    },
                )

            user_response = await client.get(
                "https://kapi.kakao.com/v2/user/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": (
                        "application/"
                        "x-www-form-urlencoded;charset=utf-8"
                    ),
                },
            )

            try:
                kakao_user = user_response.json()
            except ValueError:
                kakao_user = {
                    "raw_response": user_response.text,
                }

            if user_response.is_error:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "카카오 사용자 정보 조회 실패",
                        "status_code": user_response.status_code,
                        "kakao_response": kakao_user,
                    },
                )

    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "카카오 API 서버 연결에 실패했습니다.",
                "error": str(error),
            },
        ) from error

    kakao_account = kakao_user.get("kakao_account") or {}
    profile = kakao_account.get("profile") or {}
    properties = kakao_user.get("properties") or {}

    nickname = (
        profile.get("nickname")
        or properties.get("nickname")
        or ""
    )

    profile_image_url = (
        profile.get("profile_image_url")
        or profile.get("thumbnail_image_url")
        or properties.get("profile_image")
        or properties.get("thumbnail_image")
        or ""
    )

    email = kakao_account.get("email") or ""

    db_user = save_social_user(
        provider="kakao",
        provider_user_id=str(kakao_user.get("id") or ""),
        name=nickname or "카카오 사용자",
        email=email,
        profile_image_url=profile_image_url,
    )

    user = {
        "provider": "kakao",
        "id": db_user["id"],
        "providerUserId": db_user["provider_user_id"],
        "name": nickname,
        "email": email,
        "profileImageUrl": profile_image_url,
    }

    frontend_redirect_url = (
        f"{FRONTEND_URL.rstrip('/')}/login?auth=success"
    )

    response = RedirectResponse(
        url=frontend_redirect_url,
        status_code=302,
    )
    create_session_cookie(response, db_user["id"])

    response.delete_cookie(
        key="kakao_oauth_state",
        path="/",
    )

    return response


from anomaly_event_api import router as anomaly_event_router

app.include_router(anomaly_event_router)

from google_auth import router as google_auth_router
from guest_auth import router as guest_auth_router
from social_user_db import save_social_user
app.include_router(google_auth_router)
app.include_router(guest_auth_router)



from fastapi.staticfiles import StaticFiles
from video_inference_api import router as video_inference_router

app.include_router(video_inference_router)

app.mount(
    "/inference/results",
    StaticFiles(directory="inference_results"),
    name="inference-results",
)

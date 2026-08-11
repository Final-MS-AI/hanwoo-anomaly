import os

import psycopg
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from auth_session import create_session_cookie


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post("/guest")
def guest_login():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL이 설정되지 않았습니다.",
        )

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
                    VALUES (
                        'guest',
                        'public-demo',
                        '게스트 사용자',
                        'guest@cow-monitoring.local',
                        NULL
                    )
                    ON CONFLICT (provider, provider_user_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        email = EXCLUDED.email,
                        updated_at = NOW()
                    RETURNING
                        id,
                        provider,
                        provider_user_id,
                        name,
                        email,
                        profile_image_url
                    """,
                )
                row = cursor.fetchone()

            connection.commit()
    except psycopg.Error as exc:
        print("게스트 사용자 DB 오류:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail="게스트 사용자 생성에 실패했습니다.",
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

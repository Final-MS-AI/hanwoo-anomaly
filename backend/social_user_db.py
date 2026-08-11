import os

import psycopg


def save_social_user(
    provider: str,
    provider_user_id: str,
    name: str | None = None,
    email: str | None = None,
    profile_image_url: str | None = None,
) -> dict:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL이 설정되지 않았습니다.")

    if not provider_user_id:
        raise ValueError("provider_user_id가 없습니다.")

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
                VALUES (%s, %s, %s, %s, %s)
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
                    profile_image_url,
                    created_at,
                    updated_at
                """,
                (
                    provider,
                    str(provider_user_id),
                    name,
                    email,
                    profile_image_url,
                ),
            )

            row = cursor.fetchone()

        connection.commit()

    return {
        "id": row[0],
        "provider": row[1],
        "provider_user_id": row[2],
        "name": row[3],
        "email": row[4],
        "profile_image_url": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }

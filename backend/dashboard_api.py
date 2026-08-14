from datetime import datetime, timezone
import os

import psycopg
from fastapi import APIRouter, Cookie, HTTPException

from auth_session import read_user_id


router = APIRouter(
    prefix="/api/dashboard",
    tags=["Dashboard"],
)


@router.get("")
def get_dashboard(
    cowow_session: str | None = Cookie(default=None),
):
    # 로그인 세션에서 사용자 ID 확인
    user_id = read_user_id(cowow_session)

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL이 설정되지 않았습니다.",
        )

    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:

                # -------------------------------------------------
                # 1. 로그인 사용자가 실제 DB에 존재하는지 확인
                # -------------------------------------------------
                cursor.execute(
                    """
                    SELECT id
                    FROM public.users
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (user_id,),
                )

                if cursor.fetchone() is None:
                    raise HTTPException(
                        status_code=401,
                        detail="사용자를 찾을 수 없습니다.",
                    )

                # -------------------------------------------------
                # 2. 대시보드 요약
                # 전체 / 정상 / 주의 / 위험
                # -------------------------------------------------
                cursor.execute(
                    """
                    WITH user_cattle AS (
                        SELECT id
                        FROM public.cattle
                        WHERE user_id = %s
                    ),
                    current_severity AS (
                        SELECT
                            uc.id AS cattle_id,
                            COALESCE(
                                MAX(
                                    CASE
                                        WHEN ae.severity = 'danger' THEN 2
                                        WHEN ae.severity = 'warning' THEN 1
                                        ELSE 0
                                    END
                                ),
                                0
                            ) AS severity_level
                        FROM user_cattle uc
                        LEFT JOIN public.anomaly_events ae
                            ON ae.cattle_id = uc.id
                           AND ae.is_active = true
                        GROUP BY uc.id
                    )
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (
                            WHERE severity_level = 0
                        ) AS normal,
                        COUNT(*) FILTER (
                            WHERE severity_level = 1
                        ) AS warning,
                        COUNT(*) FILTER (
                            WHERE severity_level = 2
                        ) AS danger
                    FROM current_severity
                    """,
                    (user_id,),
                )

                summary_row = cursor.fetchone()

                # -------------------------------------------------
                # 3. 현재 이상 개체 목록
                #
                # 한 개체에 여러 활성 이상이 있으면
                # danger > warning 순으로 대표 1개만 선택
                # -------------------------------------------------
                cursor.execute(
                    """
                    WITH ranked_anomalies AS (
                        SELECT
                            c.id AS cattle_id,
                            c.national_id,
                            c.ear_tag_number,
                            ae.anomaly_type,
                            ae.severity,
                            ae.score,
                            ae.message,
                            ae.detected_at,
                            ROW_NUMBER() OVER (
                                PARTITION BY c.id
                                ORDER BY
                                    CASE
                                        WHEN ae.severity = 'danger' THEN 2
                                        WHEN ae.severity = 'warning' THEN 1
                                        ELSE 0
                                    END DESC,
                                    ae.detected_at DESC,
                                    ae.id DESC
                            ) AS rn
                        FROM public.cattle c
                        JOIN public.anomaly_events ae
                            ON ae.cattle_id = c.id
                        WHERE c.user_id = %s
                          AND ae.is_active = true
                    )
                    SELECT
                        cattle_id,
                        CASE
    WHEN LEFT(national_id, 2) = '99'
        THEN 'COW-' || RIGHT(national_id, 3)
    ELSE 'COW-' || LPAD(
        cattle_id::text,
        3,
        '0'
    )
END AS display_id,
                        national_id,
                        ear_tag_number,
                        anomaly_type,
                        severity,
                        score,
                        message,
                        detected_at
                    FROM ranked_anomalies
                    WHERE rn = 1
                    ORDER BY
                        CASE
                            WHEN severity = 'danger' THEN 2
                            WHEN severity = 'warning' THEN 1
                            ELSE 0
                        END DESC,
                        detected_at DESC
                    """,
                    (user_id,),
                )

                abnormal_rows = cursor.fetchall()

                # -------------------------------------------------
                # 4. 최근 이상 알림
                # 최근 발생 이벤트 5개
                # -------------------------------------------------
                cursor.execute(
                    """
                    SELECT
                        c.id AS cattle_id,
                        CASE
    WHEN LEFT(c.national_id, 2) = '99'
        THEN 'COW-' || RIGHT(c.national_id, 3)
    ELSE 'COW-' || LPAD(
        c.id::text,
        3,
        '0'
    )
END AS display_id,
                        ae.anomaly_type,
                        ae.severity,
                        ae.score,
                        ae.message,
                        ae.detected_at
                    FROM public.anomaly_events ae
                    JOIN public.cattle c
                        ON c.id = ae.cattle_id
                    WHERE c.user_id = %s
                    ORDER BY
                        ae.detected_at DESC,
                        ae.id DESC
                    LIMIT 5
                    """,
                    (user_id,),
                )

                recent_rows = cursor.fetchall()

    except HTTPException:
        raise

    except psycopg.Error as error:
        raise HTTPException(
            status_code=500,
            detail="대시보드 데이터 조회에 실패했습니다.",
        ) from error

    # -------------------------------------------------
    # 응답 데이터 구성
    # -------------------------------------------------

    summary = {
        "total": int(summary_row[0]),
        "normal": int(summary_row[1]),
        "warning": int(summary_row[2]),
        "danger": int(summary_row[3]),
    }

    abnormal_cattle = [
        {
            "cattle_id": row[0],
            "display_id": row[1],
            "national_id": row[2],
            "ear_tag_number": row[3],
            "anomaly_type": row[4],
            "severity": row[5],
            "score": row[6],
            "message": row[7],
            "detected_at": (
                row[8].isoformat()
                if row[8] is not None
                else None
            ),
        }
        for row in abnormal_rows
    ]

    recent_alerts = [
        {
            "cattle_id": row[0],
            "display_id": row[1],
            "anomaly_type": row[2],
            "severity": row[3],
            "score": row[4],
            "message": row[5],
            "detected_at": (
                row[6].isoformat()
                if row[6] is not None
                else None
            ),
        }
        for row in recent_rows
    ]

    return {
        "summary": summary,
        "abnormal_cattle": abnormal_cattle,
        "recent_alerts": recent_alerts,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

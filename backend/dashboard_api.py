from datetime import datetime, timezone
import os

import psycopg
from fastapi import APIRouter, Cookie, HTTPException

from auth_session import read_user_id
from anomaly_event_api import read_url


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
                    SELECT id, provider
                    FROM public.users
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (user_id,),
                )

                user_row = cursor.fetchone()
                if user_row is None:
                    raise HTTPException(
                        status_code=401,
                        detail="사용자를 찾을 수 없습니다.",
                    )
                user_provider = user_row[1]

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
                            ae.id AS anomaly_event_id,
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
                            ELSE 'COW-' || LPAD(cattle_id::text, 3, '0')
                        END AS display_id,
                        national_id,
                        ear_tag_number,
                        anomaly_type,
                        severity,
                        score,
                        message,
                        detected_at,
                        anomaly_event_id
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
                            ELSE 'COW-' || LPAD(c.id::text, 3, '0')
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

                # -------------------------------------------------
                # 5. RTSP 실시간 분석 이벤트
                # 장비 관리자와 공유 구성원에게만 노출
                # -------------------------------------------------
                cursor.execute(
                    """
                    WITH ranked_realtime AS (
                        SELECT e.id, e.device_id, e.camera_id, e.cattle_id,
                               e.status, e.behavior, e.confidence, e.detected_at,
                               e.image_blob_name, e.video_blob_name, e.metadata,
                               ROW_NUMBER() OVER (
                                   PARTITION BY
                                       e.device_id,
                                       COALESCE(
                                           NULLIF(e.cattle_id, ''),
                                           NULLIF(e.camera_id, ''),
                                           e.device_id
                                       )
                                   ORDER BY
                                       CASE
                                           WHEN e.status = 'danger' THEN 2
                                           WHEN e.status = 'warning' THEN 1
                                           ELSE 0
                                       END DESC,
                                       e.detected_at DESC
                               ) AS rn
                        FROM public.device_anomaly_events e
                        WHERE e.resolved_at IS NULL
                          -- Feeding is a normal activity and is not displayed
                          -- as an active abnormal event.
                          AND LOWER(COALESCE(e.behavior, '')) NOT IN (
                              'feeding', 'eating', '섭식', '섭식 중'
                          )
                          AND (
                            EXISTS (
                                SELECT 1 FROM public.device_owners o
                                WHERE o.device_id = e.device_id
                                  AND o.user_id = %s
                            )
                            OR EXISTS (
                                SELECT 1 FROM public.device_members m
                                WHERE m.device_id = e.device_id
                                  AND m.user_id = %s
                            )
                            OR (
                                %s = 'guest'
                                AND e.device_id = %s
                                AND NOT EXISTS (
                                    SELECT 1 FROM public.device_owners o2
                                    WHERE o2.device_id = e.device_id
                                )
                            )
                          )
                    )
                    SELECT id, device_id, camera_id, cattle_id,
                           status, behavior, confidence, detected_at,
                           image_blob_name, video_blob_name, metadata
                    FROM ranked_realtime
                    WHERE rn = 1
                    ORDER BY detected_at DESC
                    LIMIT 100
                    """,
                    (
                        user_id,
                        user_id,
                        user_provider,
                        os.getenv("ESP32_PHYSICAL_DEVICE_ID", "ESP32-01"),
                    ),
                )
                realtime_rows = cursor.fetchall()

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
            "anomaly_event_id": str(row[9]),
            "detected_at": (
                row[8].isoformat()
                if row[8] is not None
                else None
            ),
        }
        for row in abnormal_rows
    ]

    behavior_labels = {
        "prolonged_standing": "장시간 서 있음",
        "prolonged_lying": "장시간 누움",
        "standing": "서 있음",
        "lying": "누워 있음",
        "walking": "걷는 중",
    }
    realtime_cattle = []
    for row in realtime_rows:
        national_id = row[3]
        display_id = (
            f"COW-{national_id[-3:]}"
            if national_id and national_id.startswith("99")
            else (national_id or f"{row[2] or row[1]} 미확인 개체")
        )
        realtime_cattle.append(
            {
                "cattle_id": str(row[0]),
                "display_id": display_id,
                "national_id": row[3],
                "track_id": (row[10] or {}).get("trackId"),
                "ear_tag_number": None,
                "anomaly_type": row[5],
                "severity": row[4],
                "score": row[6],
                "message": behavior_labels.get(row[5], row[5] or "이상 행동"),
                "anomaly_event_id": str(row[0]),
                "detected_at": row[7].isoformat() if row[7] is not None else None,
                "image_url": read_url(row[8]),
                "video_url": read_url(row[9]),
                "device_id": row[1],
                "camera_id": row[2],
            }
        )

    abnormal_cattle.extend(realtime_cattle)
    abnormal_cattle.sort(
        key=lambda item: (
            2 if item["severity"] == "danger" else 1,
            item["detected_at"] or "",
        ),
        reverse=True,
    )

    # 같은 개체의 여러 이벤트는 가장 높은 현재 상태 한 건으로 계산한다.
    severity_by_cattle = {}
    for item in abnormal_cattle:
        cattle_key = item["display_id"]
        severity_level = 2 if item["severity"] == "danger" else 1
        severity_by_cattle[cattle_key] = max(
            severity_by_cattle.get(cattle_key, 0),
            severity_level,
        )
    summary["danger"] = sum(level == 2 for level in severity_by_cattle.values())
    summary["warning"] = sum(level == 1 for level in severity_by_cattle.values())
    summary["total"] = max(summary["total"], len(severity_by_cattle))
    summary["normal"] = max(
        summary["total"] - summary["warning"] - summary["danger"],
        0,
    )

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

    recent_alerts.extend(
        {
            "cattle_id": str(row[0]),
            "display_id": (
                f"COW-{row[3][-3:]}"
                if row[3] and row[3].startswith("99")
                else (row[3] or f"{row[2] or row[1]} 미확인 개체")
            ),
            "anomaly_type": row[5],
            "severity": row[4],
            "score": row[6],
            "message": behavior_labels.get(row[5], row[5] or "이상 행동"),
            "detected_at": row[7].isoformat() if row[7] is not None else None,
        }
        for row in realtime_rows
    )
    recent_alerts.sort(key=lambda item: item["detected_at"] or "", reverse=True)
    recent_alerts = recent_alerts[:5]

    return {
        "summary": summary,
        "abnormal_cattle": abnormal_cattle,
        "recent_alerts": recent_alerts,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

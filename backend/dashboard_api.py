from datetime import datetime, timezone
import os

import psycopg
from fastapi import APIRouter, Cookie, HTTPException

from auth_session import read_user_id
from anomaly_event_api import read_url
from cattle_attention_policy import (
    BASELINE_REQUIRED_VALID_DAYS,
    FEED_BUNK_WARNING_DECREASE_RATIO,
    LYING_WARNING_DECREASE_RATIO,
    MIN_VALID_OBSERVATION_SEC,
)


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

    analysis_rows = []
    latest_analysis_date = None

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

                # -------------------------------------------------
                # 6. 오른쪽 패널용 최근 감지 행동
                #
                # - abnormal 여부와 관계없이 최근 행동 이벤트를 사용
                # - feeding 이벤트도 포함
                # - national_id가 확인된 개체만 노출
                # - 개체별 최신 1건
                # -------------------------------------------------
                cursor.execute(
                    """
                    WITH ranked_behavior AS (
                        SELECT e.id, e.device_id, e.camera_id, e.cattle_id,
                               e.status, e.behavior, e.confidence, e.detected_at,
                               e.image_blob_name, e.video_blob_name, e.metadata,
                               ROW_NUMBER() OVER (
                                   PARTITION BY e.cattle_id
                                   ORDER BY e.detected_at DESC, e.created_at DESC
                               ) AS rn
                        FROM public.device_anomaly_events e
                        WHERE NULLIF(e.cattle_id, '') IS NOT NULL
                          AND e.resolved_at IS NULL
                          AND (e.detected_at AT TIME ZONE 'Asia/Seoul')::date
                              = (now() AT TIME ZONE 'Asia/Seoul')::date
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
                    FROM ranked_behavior
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
                recent_behavior_rows = cursor.fetchall()

                # -------------------------------------------------
                # 7. 왼쪽 패널용 COWOW 전용 일별 주의 분석
                #
                # 기존 팀 behavior_* / anomaly_events를 수정하지 않고
                # public.cattle_attention_daily_analysis만 읽는다.
                # 테이블 미배포 환경에서도 기존 dashboard API는 계속 동작한다.
                # -------------------------------------------------
                cursor.execute(
                    "SELECT to_regclass('public.cattle_attention_daily_analysis')"
                )
                analysis_table_row = cursor.fetchone()
                analysis_table_exists = bool(
                    analysis_table_row and analysis_table_row[0]
                )

                if analysis_table_exists:
                    # 대표 분석일은 현재 사용자의 분석 결과 중 가장 최신 날짜를 사용한다.
                    # 최신 날짜에 일부 개체 결과가 없더라도 과거의 더 완전한 날짜로 되돌아가지 않는다.
                    cursor.execute(
                        """
                        SELECT a.analysis_date, COUNT(DISTINCT a.cattle_id) AS coverage
                        FROM public.cattle_attention_daily_analysis a
                        JOIN public.cattle c ON c.id = a.cattle_id
                        WHERE (
                            c.user_id = %s
                            OR c.user_id IN (
                                SELECT o.user_id
                                FROM public.device_members m
                                JOIN public.device_owners o
                                  ON o.device_id = m.device_id
                                WHERE m.user_id = %s
                            )
                          )
                          AND (
                            COALESCE(c.status, 'active') = 'active'
                            OR (%s = 'guest' AND c.status = 'demo')
                          )
                        GROUP BY a.analysis_date
                        ORDER BY a.analysis_date DESC
                        LIMIT 1
                        """,
                        (user_id, user_id, user_provider),
                    )
                    date_row = cursor.fetchone()
                    if date_row:
                        latest_analysis_date = date_row[0]
                        analysis_coverage = int(date_row[1])
                    else:
                        analysis_coverage = 0
                else:
                    analysis_coverage = 0

                if analysis_table_exists and latest_analysis_date is not None:
                    cursor.execute(
                        """
                        SELECT
                            a.analysis_id,
                            c.id AS cattle_id,
                            c.national_id,
                            CASE
                                WHEN LEFT(c.national_id, 2) = '99'
                                    THEN 'COW-' || RIGHT(c.national_id, 3)
                                ELSE 'COW-' || LPAD(c.id::text, 3, '0')
                            END AS display_id,
                            %s::date AS analysis_date,
                            COALESCE(a.status, 'insufficient_baseline') AS status,
                            COALESCE(a.primary_metric, '일별 분석 결과 없음') AS primary_metric,
                            a.primary_change_ratio,
                            COALESCE(a.baseline_valid_days, 0) AS baseline_valid_days,
                            COALESCE(a.baseline_required_days, %s) AS baseline_required_days,
                            COALESCE(a.streak_days, 0) AS streak_days,
                            COALESCE(a.valid_observation_sec, 0) AS valid_observation_sec,
                            COALESCE(a.feed_bunk_duration_sec, 0) AS feed_bunk_duration_sec,
                            a.feed_bunk_ratio,
                            a.baseline_feed_bunk_ratio,
                            a.feed_bunk_change_ratio,
                            COALESCE(a.lying_duration_sec, 0) AS lying_duration_sec,
                            a.lying_ratio,
                            a.baseline_lying_ratio,
                            a.lying_change_ratio,
                            COALESCE(a.standing_duration_sec, 0) AS standing_duration_sec,
                            a.standing_ratio,
                            a.baseline_standing_ratio,
                            a.standing_change_ratio,
                            COALESCE(a.walking_duration_sec, 0) AS walking_duration_sec,
                            a.walking_ratio,
                            a.baseline_walking_ratio,
                            a.walking_change_ratio,
                            COALESCE(
                                a.data_quality_reason,
                                '해당 분석일의 분석 결과가 없습니다.'
                            ) AS data_quality_reason,
                            COALESCE(a.source, 'missing') AS source,
                            COALESCE(a.warning_reasons, '[]'::jsonb) AS warning_reasons
                        FROM public.cattle c
                        LEFT JOIN LATERAL (
                            SELECT
                                d.id AS analysis_id,
                                d.status, d.primary_metric, d.primary_change_ratio,
                                d.baseline_valid_days, d.baseline_required_days,
                                d.streak_days, d.valid_observation_sec,
                                d.feed_bunk_duration_sec, d.feed_bunk_ratio,
                                d.baseline_feed_bunk_ratio, d.feed_bunk_change_ratio,
                                d.lying_duration_sec, d.lying_ratio,
                                d.baseline_lying_ratio, d.lying_change_ratio,
                                d.standing_duration_sec, d.standing_ratio,
                                d.baseline_standing_ratio, d.standing_change_ratio,
                                d.walking_duration_sec, d.walking_ratio,
                                d.baseline_walking_ratio, d.walking_change_ratio,
                                d.data_quality_reason, d.source, d.warning_reasons
                            FROM public.cattle_attention_daily_analysis d
                            WHERE d.cattle_id = c.id
                              AND d.analysis_date = %s
                            ORDER BY
                                CASE WHEN d.source = 'computed' THEN 0 ELSE 1 END,
                                d.updated_at DESC, d.id DESC
                            LIMIT 1
                        ) a ON TRUE
                        WHERE (
                            c.user_id = %s
                            OR c.user_id IN (
                                SELECT o.user_id
                                FROM public.device_members m
                                JOIN public.device_owners o
                                  ON o.device_id = m.device_id
                                WHERE m.user_id = %s
                            )
                          )
                          AND (
                            COALESCE(c.status, 'active') = 'active'
                            OR (%s = 'guest' AND c.status = 'demo')
                          )
                        ORDER BY c.id
                        """,
                        (
                            latest_analysis_date,
                            BASELINE_REQUIRED_VALID_DAYS,
                            latest_analysis_date,
                            user_id,
                            user_id,
                            user_provider,
                        ),
                    )
                    analysis_rows = cursor.fetchall()
                else:
                    cursor.execute(
                        """
                        SELECT
                            NULL::bigint, c.id, c.national_id,
                            CASE
                                WHEN LEFT(c.national_id, 2) = '99'
                                    THEN 'COW-' || RIGHT(c.national_id, 3)
                                ELSE 'COW-' || LPAD(c.id::text, 3, '0')
                            END,
                            NULL::date, 'insufficient_baseline'::text,
                            '일별 분석 결과 없음'::text, NULL::double precision,
                            0::integer, 10::integer, 0::integer,
                            0::double precision, 0::double precision,
                            NULL::double precision, NULL::double precision, NULL::double precision,
                            0::double precision, NULL::double precision, NULL::double precision, NULL::double precision,
                            0::double precision, NULL::double precision, NULL::double precision, NULL::double precision,
                            0::double precision, NULL::double precision, NULL::double precision, NULL::double precision,
                            'COWOW 왼쪽 일별 분석 결과가 아직 없습니다.'::text,
                            'missing'::text, '[]'::jsonb
                        FROM public.cattle c
                        WHERE (
                            c.user_id = %s
                            OR c.user_id IN (
                                SELECT o.user_id
                                FROM public.device_members m
                                JOIN public.device_owners o
                                  ON o.device_id = m.device_id
                                WHERE m.user_id = %s
                            )
                          )
                          AND (
                            COALESCE(c.status, 'active') = 'active'
                            OR (%s = 'guest' AND c.status = 'demo')
                          )
                        ORDER BY c.id
                        """,
                        (user_id, user_id, user_provider),
                    )
                    analysis_rows = cursor.fetchall()

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

    # 기존 abnormal_cattle/recent_alerts의 표시 의미는 그대로 유지한다.
    behavior_labels = {
        "prolonged_standing": "장시간 서 있음",
        "prolonged_lying": "장시간 누움",
        "standing": "서 있음",
        "lying": "누워 있음",
        "walking": "걷는 중",
        "feeding": "섭식 중",
    }

    # 새 오른쪽 '최근 감지 행동' 패널에서만 사용자용 행동명을 4개 행동군으로 단순화한다.
    # 팀 VM2는 feeding/eating/섭식 계열을 head_down으로 노출할 수 있으므로
    # 대시보드 표시에서만 head_down을 섭식 계열로 묶는다.
    def recent_behavior_label(value):
        key = str(value or "").strip().lower()
        if not key:
            return "행동 정보 없음"
        if "standing" in key:
            return "서 있음"
        if "lying" in key:
            return "누워 있음"
        if "walking" in key:
            return "걷는 중"
        if (
            "feeding" in key
            or "eating" in key
            or "head_down" in key
            or "섭식" in key
        ):
            return "섭식 중"
        return value
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

    recent_behavior = []
    for row in recent_behavior_rows:
        national_id = row[3]
        display_id = (
            f"COW-{national_id[-3:]}"
            if national_id and national_id.startswith("99")
            else national_id
        )
        if not display_id:
            continue

        raw_behavior = row[5]
        recent_behavior.append(
            {
                "id": str(row[0]),
                "anomaly_event_id": str(row[0]),
                "display_id": display_id,
                "national_id": national_id,
                "track_id": (row[10] or {}).get("trackId"),
                "status": row[4],
                "behavior": raw_behavior,
                "behavior_label": recent_behavior_label(raw_behavior),
                "confidence": row[6],
                "detected_at": (
                    row[7].isoformat()
                    if row[7] is not None
                    else None
                ),
                "image_url": read_url(row[8]),
                "video_url": read_url(row[9]),
                "device_id": row[1],
                "camera_id": row[2],
            }
        )

    # 공개 게스트는 실제 CCTV/device_anomaly_events를 노출하지 않는다.
    # 대신 오른쪽 패널의 UX를 체험할 수 있도록 API 응답에서만 고정 예시 행동을 제공한다.
    # DB에는 가짜 device_anomaly_events를 추가하지 않으며 이미지/영상/피드백용 event id도 만들지 않는다.
    if user_provider == "guest":
        guest_behavior = [
            ("990000000001", "standing"),
            ("990000000002", "feeding"),
            ("990000000003", "lying"),
            ("990000000004", "walking"),
            ("990000000005", "standing"),
            ("990000000006", "feeding"),
        ]
        recent_behavior = [
            {
                "id": f"guest-demo-{national_id[-3:]}",
                "anomaly_event_id": None,
                "display_id": f"COW-{national_id[-3:]}",
                "national_id": national_id,
                "track_id": None,
                "status": "demo",
                "behavior": behavior,
                "behavior_label": recent_behavior_label(behavior),
                "confidence": None,
                "detected_at": None,
                "image_url": None,
                "video_url": None,
                "device_id": None,
                "camera_id": None,
            }
            for national_id, behavior in guest_behavior
        ]

    # 게스트 왼쪽 일별 분석은 COW-001~006만 노출한다.
    # 기존 guest-demo 60두 DB 데이터는 삭제하거나 변경하지 않는다.
    if user_provider == "guest":
        guest_analysis_national_ids = {
            "990000000001",
            "990000000002",
            "990000000003",
            "990000000004",
            "990000000005",
            "990000000006",
        }
        analysis_rows = [
            row
            for row in analysis_rows
            if row[2] in guest_analysis_national_ids
        ]

    def _ratio_percent(value):
        return None if value is None else round(float(value) * 100.0, 1)

    def _minutes(value):
        return round(float(value or 0) / 60.0, 1)

    analysis_cattle = []
    for row in analysis_rows:
        metrics = [
            {
                "key": "feed_bunk",
                "label": "급이대 체류",
                "duration_min": _minutes(row[12]),
                "current_ratio_percent": _ratio_percent(row[13]),
                "baseline_ratio_percent": _ratio_percent(row[14]),
                "change_ratio_percent": _ratio_percent(row[15]),
                "is_warning_metric": row[15] is not None and float(row[15]) <= -FEED_BUNK_WARNING_DECREASE_RATIO,
            },
            {
                "key": "lying",
                "label": "누움",
                "duration_min": _minutes(row[16]),
                "current_ratio_percent": _ratio_percent(row[17]),
                "baseline_ratio_percent": _ratio_percent(row[18]),
                "change_ratio_percent": _ratio_percent(row[19]),
                "is_warning_metric": row[19] is not None and float(row[19]) <= -LYING_WARNING_DECREASE_RATIO,
            },
            {
                "key": "standing",
                "label": "기립",
                "duration_min": _minutes(row[20]),
                "current_ratio_percent": _ratio_percent(row[21]),
                "baseline_ratio_percent": _ratio_percent(row[22]),
                "change_ratio_percent": _ratio_percent(row[23]),
                "is_warning_metric": False,
            },
            {
                "key": "walking",
                "label": "걷기",
                "duration_min": _minutes(row[24]),
                "current_ratio_percent": _ratio_percent(row[25]),
                "baseline_ratio_percent": _ratio_percent(row[26]),
                "change_ratio_percent": _ratio_percent(row[27]),
                "is_warning_metric": False,
            },
        ]
        analysis_cattle.append(
            {
                "analysis_id": str(row[0]) if row[0] is not None else None,
                "cattle_id": row[1],
                "national_id": row[2],
                "display_id": row[3],
                "analysis_date": row[4].isoformat() if row[4] is not None else None,
                "status": row[5],
                "primary_metric": row[6],
                "change_ratio": (
                    None if row[7] is None else round(float(row[7]) * 100.0, 1)
                ),
                "baseline_valid_days": int(row[8] or 0),
                "baseline_required_days": int(row[9] or BASELINE_REQUIRED_VALID_DAYS),
                "streak_days": int(row[10] or 0),
                "valid_observation_sec": float(row[11] or 0),
                "valid_observation_minutes": _minutes(row[11]),
                "metrics": metrics,
                "insufficient_reason": row[28],
                "source": row[29],
                "warning_reasons": row[30] or [],
            }
        )

    analysis_summary = {
        "total": len(analysis_cattle),
        "warning": sum(1 for item in analysis_cattle if item["status"] == "warning"),
        "insufficient": sum(
            1
            for item in analysis_cattle
            if item["status"] in {"insufficient_data", "insufficient_baseline"}
        ),
    }
    analysis_summary["normal"] = max(
        analysis_summary["total"]
        - analysis_summary["warning"]
        - analysis_summary["insufficient"],
        0,
    )

    return {
        # 기존 응답은 다른 화면/기능과의 호환을 위해 유지한다.
        "summary": summary,
        "abnormal_cattle": abnormal_cattle,
        "recent_alerts": recent_alerts,

        # 새 대시보드 오른쪽 패널 전용. 게스트는 DB가 아닌 고정 예시 응답이다.
        "recent_behavior": recent_behavior,
        "recent_behavior_mode": "demo" if user_provider == "guest" else "live",

        # COWOW 왼쪽 전용 분석. 기존 behavior_* / anomaly_events와 독립.
        # cattle이 전체 개체 기준이며 분석 결과는 LEFT JOIN한다.
        "analysis_cattle": analysis_cattle,
        "analysis_summary": analysis_summary,
        "analysis_date": (
            latest_analysis_date.isoformat()
            if latest_analysis_date is not None
            else None
        ),
        "analysis_coverage": analysis_coverage,
        "analysis_policy": {
            "baseline_required_valid_days": BASELINE_REQUIRED_VALID_DAYS,
            "feed_bunk_warning_decrease_percent": round(
                FEED_BUNK_WARNING_DECREASE_RATIO * 100.0, 1
            ),
            "lying_warning_decrease_percent": round(
                LYING_WARNING_DECREASE_RATIO * 100.0, 1
            ),
            "minimum_valid_observation_sec": MIN_VALID_OBSERVATION_SEC,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

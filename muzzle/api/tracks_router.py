"""트랙 ↔ 개체 바인딩 (ID 역전파).

바인딩 1행이 해당 트랙의 과거 관측 전체에 소급 적용된다.
과거 행을 UPDATE 하지 않으므로 해제도 행 하나 비활성화로 끝난다.
"""
import os

import psycopg
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query

load_dotenv("/home/azureuser/muzzle_api/.env")
DSN = os.getenv("DATABASE_URL")

OPER_THRESHOLD = 0.70   # THRESHOLD_POLICY.md 실영상 운영 임계값

router = APIRouter(tags=["tracks"])


def conn():
    return psycopg.connect(DSN)


@router.post("/tracks/{segment_id}/bind")
def bind(segment_id: int,
         national_id: str = Query(..., min_length=1),
         similarity: float = Query(...),
         source: str = Query("muzzle"),
         force: bool = Query(False)):
    """트랙에 개체를 바인딩한다."""
    if similarity < OPER_THRESHOLD:
        raise HTTPException(422, {
            "error": "below_threshold",
            "similarity": similarity,
            "threshold": OPER_THRESHOLD,
            "message": "임계값 미만이므로 ID를 부여하지 않는다",
        })

    with conn() as c:
        if not c.execute("SELECT 1 FROM public.track_segment WHERE id=%s",
                         (segment_id,)).fetchone():
            raise HTTPException(404, "segment_not_found")

        row = c.execute("""SELECT id, national_id FROM public.track_identity_binding
                           WHERE segment_id=%s AND is_active""", (segment_id,)).fetchone()
        replaced = None
        if row:
            if row[1] == national_id:
                return {"segment_id": segment_id, "national_id": national_id,
                        "status": "already_bound", "affected_observations": _count(c, segment_id)}
            if not force:
                raise HTTPException(409, {
                    "error": "conflict",
                    "bound_national_id": row[1],
                    "requested_national_id": national_id,
                    "message": "이미 다른 개체로 바인딩됨. 교체하려면 force=true",
                })
            c.execute("UPDATE public.track_identity_binding SET is_active=false WHERE id=%s",
                      (row[0],))
            replaced = row[1]

        cattle = c.execute("SELECT id FROM public.cattle WHERE national_id=%s LIMIT 1",
                           (national_id,)).fetchone()
        c.execute("""INSERT INTO public.track_identity_binding
                     (segment_id, cattle_id, national_id, source, similarity)
                     VALUES (%s,%s,%s,%s,%s)""",
                  (segment_id, cattle[0] if cattle else None, national_id, source, similarity))
        n = _count(c, segment_id)
        c.commit()

    return {"segment_id": segment_id, "national_id": national_id, "similarity": similarity,
            "status": "replaced" if replaced else "bound",
            "replaced_national_id": replaced, "affected_observations": n}


@router.delete("/tracks/{segment_id}/bind")
def unbind(segment_id: int):
    """바인딩을 해제한다. 행은 남기고 비활성화한다."""
    with conn() as c:
        n = c.execute("""UPDATE public.track_identity_binding SET is_active=false
                         WHERE segment_id=%s AND is_active""", (segment_id,)).rowcount
        c.commit()
    if not n:
        raise HTTPException(404, "no_active_binding")
    return {"segment_id": segment_id, "status": "unbound"}


@router.get("/tracks/{segment_id}")
def get_track(segment_id: int):
    with conn() as c:
        s = c.execute("""SELECT id, camera_id, session_id, track_id,
                                started_at, ended_at, frame_count, source_video
                         FROM public.track_segment WHERE id=%s""", (segment_id,)).fetchone()
        if not s:
            raise HTTPException(404, "segment_not_found")
        b = c.execute("""SELECT national_id, source, similarity, decided_at
                         FROM public.track_identity_binding
                         WHERE segment_id=%s AND is_active""", (segment_id,)).fetchone()
    return {
        "segment_id": s[0], "camera_id": s[1], "session_id": s[2], "track_id": s[3],
        "started_at": s[4], "ended_at": s[5], "frame_count": s[6], "source_video": s[7],
        "binding": {"national_id": b[0], "source": b[1],
                    "similarity": b[2], "decided_at": b[3]} if b else None,
    }


@router.get("/tracks")
def list_tracks(camera_id: str | None = None, bound: bool | None = None, limit: int = 50):
    where, params = [], []
    if camera_id is not None:
        where.append("s.camera_id = %s")
        params.append(camera_id)
    if bound is True:
        where.append("b.national_id IS NOT NULL")
    elif bound is False:
        where.append("b.national_id IS NULL")

    q = """SELECT s.id, s.camera_id, s.track_id, s.started_at, s.frame_count, b.national_id
           FROM public.track_segment s
           LEFT JOIN public.track_identity_binding b
             ON b.segment_id = s.id AND b.is_active"""
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY s.id DESC LIMIT %s"
    params.append(limit)

    with conn() as c:
        rows = c.execute(q, params).fetchall()
    return {"count": len(rows), "tracks": [
        {"segment_id": r[0], "camera_id": r[1], "track_id": r[2],
         "started_at": r[3], "frame_count": r[4], "national_id": r[5]} for r in rows]}


def _count(c, segment_id: int) -> int:
    return c.execute("SELECT count(*) FROM public.track_observation WHERE segment_id=%s",
                     (segment_id,)).fetchone()[0]

# 테스트 데이터는 지우지 않고 session_id 접두어로 격리한다.
#   test_*  검증용 — 기본 응답에서 제외
#   demo_*  발표용, 그 외 실데이터 — 노출
# 새 컬럼을 만들지 않는 이유: ALTER 는 팀 공용 DB 에 위험하고(2026-08-04),
# session_id 는 이미 "추적 1회 실행 단위"라 의미가 어긋나지 않는다.
TEST_SESSION_PREFIX = "test_"


@router.get("/cattle/{national_id}/timeline")
def cattle_timeline(national_id: str,
                    start: str | None = None,
                    end: str | None = None,
                    include_test: bool = Query(False, description="test_* 세션 포함 여부"),
                    limit: int = Query(2000, ge=1, le=20000)):
    """개체별 관측 시계열. 이상행동 파트 인계용 최종 산출물.

    바인딩 이전 구간도 포함된다 — 뷰가 JOIN 으로 소급 적용하기 때문이다.
    선택 필터는 SQL 에 항상 넣지 않고 필요한 것만 조립한다 (IndeterminateDatatype 회피).
    """
    where, params = ["national_id = %s"], [national_id]
    if not include_test:
        where.append("session_id NOT LIKE %s")
        params.append(TEST_SESSION_PREFIX + "%")
    if start is not None:
        where.append("ts >= %s")
        params.append(start)
    if end is not None:
        where.append("ts <= %s")
        params.append(end)
    cond = " AND ".join(where)

    with conn() as c:
        segs = c.execute(f"""
            SELECT segment_id, camera_id, track_id, session_id,
                   min(ts), max(ts), count(*), max(similarity), max(source)
            FROM public.v_identified_track_observation
            WHERE {cond}
            GROUP BY segment_id, camera_id, track_id, session_id
            ORDER BY min(ts)""", params).fetchall()

        rows = c.execute(f"""
            SELECT ts, camera_id, segment_id, track_id, frame_idx,
                   bbox_x, bbox_y, bbox_w, bbox_h, conf, similarity,
                   behavior, behavior_conf
            FROM public.v_identified_track_observation
            WHERE {cond}
            ORDER BY ts
            LIMIT %s""", params + [limit]).fetchall()

    return {
        "national_id": national_id,
        "include_test": include_test,
        "segment_count": len(segs),
        "observation_count": len(rows),
        "truncated": len(rows) >= limit,
        "segments": [
            {"segment_id": s[0], "camera_id": s[1], "track_id": s[2], "session_id": s[3],
             "started_at": s[4], "ended_at": s[5], "observations": s[6],
             "similarity": s[7], "source": s[8]} for s in segs],
        "observations": [
            {"ts": r[0], "camera_id": r[1], "segment_id": r[2], "track_id": r[3],
             "frame_idx": r[4], "bbox": [r[5], r[6], r[7], r[8]],
             "conf": r[9], "similarity": r[10],
             "behavior": r[11], "behavior_conf": r[12]} for r in rows],
    }

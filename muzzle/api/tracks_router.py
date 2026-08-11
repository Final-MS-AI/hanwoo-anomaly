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
"""초크포인트 구역 (track_zone) — 사용자가 CCTV 화면에서 직접 지정한 다각형.

좌표는 정규화(0~1)로 저장한다. bbox 는 픽셀이므로 판정 시 frame_w/h 로 환산한다.
재지정은 삭제가 아니라 '이전 행 비활성화 + 새 행 INSERT' 다. 이력이 남고 되돌릴 수 있다.
track_identity_binding 과 동일한 패턴이다.
"""
import json
import os

import psycopg
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

load_dotenv("/home/azureuser/muzzle_api/.env")
DSN = os.getenv("DATABASE_URL")

router = APIRouter(tags=["zones"])

COLS = ("id, name, device_id, camera_id, frame_w, frame_h, poly, anchor,"
        " is_active, created_at")


def conn():
    return psycopg.connect(DSN)


def _row(r):
    return {
        "id": r[0], "name": r[1], "device_id": r[2], "camera_id": r[3],
        "frame_w": r[4], "frame_h": r[5], "poly": r[6], "anchor": r[7],
        "is_active": r[8],
        "created_at": r[9].isoformat() if r[9] else None,
    }


class ZoneIn(BaseModel):
    name: str = "top"
    frame_w: int
    frame_h: int
    poly: list
    anchor: str = "topright"
    camera_id: str = "A"
    device_id: str | None = None


def _validate(z: ZoneIn):
    """저장 전에 막는다. 잘못된 구역이 들어가면 핸드오프가 조용히 틀린다."""
    if z.frame_w <= 0 or z.frame_h <= 0:
        raise HTTPException(422, {"error": "bad_frame",
                                  "message": "frame_w/h 는 양수여야 한다"})
    if not isinstance(z.poly, list) or len(z.poly) < 3:
        raise HTTPException(422, {"error": "too_few_points",
                                  "points": len(z.poly) if isinstance(z.poly, list) else 0,
                                  "message": "다각형은 꼭짓점 3개 이상"})
    clean = []
    for i, p in enumerate(z.poly):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise HTTPException(422, {"error": "bad_point", "index": i,
                                      "message": "각 꼭짓점은 [x, y] 형태"})
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError):
            raise HTTPException(422, {"error": "bad_point", "index": i,
                                      "message": "좌표가 숫자가 아니다"})
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise HTTPException(422, {"error": "not_normalized", "index": i,
                                      "point": [x, y],
                                      "message": "좌표는 0~1 정규화 값이어야 한다."
                                                 " 픽셀 좌표를 그대로 보내지 말 것"})
        clean.append([round(x, 4), round(y, 4)])
    if not z.anchor.strip():
        raise HTTPException(422, {"error": "bad_anchor",
                                  "message": "anchor 가 비어 있다"})
    return clean


@router.get("/zones")
def list_zones(camera_id: str = Query(None),
               device_id: str = Query(None),
               include_inactive: bool = Query(False)):
    """구역 목록. 기본은 활성만."""
    where, args = [], []
    if not include_inactive:
        where.append("is_active")
    if camera_id:
        where.append("camera_id = %s")
        args.append(camera_id)
    if device_id:
        where.append("device_id = %s")
        args.append(device_id)
    sql = f"SELECT {COLS} FROM public.track_zone"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, args)
        rows = [_row(r) for r in cur.fetchall()]
    return {"count": len(rows), "zones": rows}


@router.get("/zones/{name}")
def get_zone(name: str,
             camera_id: str = Query("A"),
             device_id: str = Query(None)):
    """이름으로 활성 구역 1건. zones.py 가 이것을 부른다."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            f"SELECT {COLS} FROM public.track_zone"
            " WHERE is_active AND name = %s AND camera_id = %s"
            "   AND COALESCE(device_id, '') = COALESCE(%s, '')"
            " ORDER BY id DESC LIMIT 1",
            (name, camera_id, device_id))
        r = cur.fetchone()
    if not r:
        raise HTTPException(404, "zone_not_found")
    return _row(r)


@router.post("/zones")
def create_zone(z: ZoneIn):
    """구역 등록. 같은 키의 활성 구역이 있으면 비활성화하고 새로 넣는다."""
    poly = _validate(z)
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE public.track_zone SET is_active = FALSE, updated_at = now()"
            " WHERE is_active AND name = %s AND camera_id = %s"
            "   AND COALESCE(device_id, '') = COALESCE(%s, '')"
            " RETURNING id",
            (z.name, z.camera_id, z.device_id))
        replaced = [r[0] for r in cur.fetchall()]
        cur.execute(
            "INSERT INTO public.track_zone"
            " (name, device_id, camera_id, frame_w, frame_h, poly, anchor)"
            " VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)"
            f" RETURNING {COLS}",
            (z.name, z.device_id, z.camera_id, z.frame_w, z.frame_h,
             json.dumps(poly), z.anchor))
        row = _row(cur.fetchone())
        c.commit()
    return {"status": "replaced" if replaced else "created",
            "replaced_ids": replaced, "points": len(poly), "zone": row}


@router.delete("/zones/{zone_id}")
def deactivate_zone(zone_id: int):
    """비활성화. 행은 지우지 않는다."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE public.track_zone SET is_active = FALSE, updated_at = now()"
            " WHERE id = %s AND is_active RETURNING id",
            (zone_id,))
        r = cur.fetchone()
        c.commit()
    if not r:
        raise HTTPException(404, "zone_not_found_or_already_inactive")
    return {"status": "deactivated", "id": zone_id}
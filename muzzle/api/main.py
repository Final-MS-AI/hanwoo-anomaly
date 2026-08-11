"""
비문 개체식별 API
  POST /muzzle/enroll    이미지(1~5장) + 가축이력번호 -> 임베딩 등록
  POST /muzzle/identify  이미지 1장 -> {cattle_id, similarity, decision}
threshold: float = Form(0.70)):   # 실촬영 CCTV 도메인 기본값 (THRESHOLD_POLICY.md §2)
"""
import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pgvector.psycopg import register_vector

from encoder_onnx import MuzzleEncoderONNX, DEFAULT_THRESHOLD, MODEL_VERSION

CONSISTENCY_MIN = 0.45  # 운영 임계값과 동일

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(".env 에 DATABASE_URL 이 없습니다")

app = FastAPI(title="Muzzle Identification API", docs_url="/muzzle/docs", openapi_url="/muzzle/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

encoder = MuzzleEncoderONNX()


@contextmanager
def get_conn():
    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        yield conn


@app.get("/muzzle/health")
def health():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.enrollment WHERE is_active")
        n = cur.fetchone()[0]
    return {"status": "ok", "enrolled": n,
            "threshold": DEFAULT_THRESHOLD, "model": MODEL_VERSION}


@app.post("/muzzle/enroll")
async def enroll(national_id: str = Form(...),
                 barn_id: str = Form(None),
                 files: list[UploadFile] = File(...)):
    """개체 등록. 서로 다른 시점에 찍은 3~5장을 권장한다."""
    if not files:
        raise HTTPException(400, "이미지가 없습니다")
    if len(national_id) != 12 or not national_id.isdigit():
        raise HTTPException(400, "가축이력번호는 숫자 12자리여야 합니다")

    blobs = [await f.read() for f in files]
    try:
        # ── 등록 이미지 일관성 검사 (개체 식별 파트) ──
        # 서로 다른 개체 사진이 섞이면 평균이 '아무 소도 아닌 벡터'가 된다.
        _muzzle_consistency = None
        if len(blobs) >= 2:
            _vs = []
            for _b in blobs:
                _v = np.asarray(encoder.enroll([_b]), dtype=np.float32).reshape(-1)
                _vs.append(_v / (float(np.linalg.norm(_v)) + 1e-12))
            _pairs = [float(_vs[_i] @ _vs[_j])
                      for _i in range(len(_vs)) for _j in range(_i + 1, len(_vs))]
            _muzzle_consistency = round(min(_pairs), 4)
            if _muzzle_consistency < CONSISTENCY_MIN:
                raise HTTPException(status_code=422, detail={
                    "error": "inconsistent_images",
                    "message": f"업로드한 사진들이 서로 다른 개체로 보입니다 "
                               f"(최저 일치도 {_muzzle_consistency}). "
                               f"같은 소의 코를 여러 각도로 찍은 사진만 넣어주세요.",
                    "min_pair_similarity": _muzzle_consistency,
                    "required": CONSISTENCY_MIN,
                })
        vec = encoder.enroll(blobs)
    except ValueError as e:
        raise HTTPException(400, str(e))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO cattle (national_id, barn_id) VALUES (%s, %s)
            ON CONFLICT (national_id) DO UPDATE SET national_id = EXCLUDED.national_id
            RETURNING id
        """, (national_id, barn_id))
        cattle_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO public.enrollment (cattle_id, embedding, quality_score)
            VALUES (%s, %s, %s) RETURNING id
        """, (cattle_id, vec, None))
        enroll_id = cur.fetchone()[0]
        conn.commit()

    return {"cattle_id": cattle_id, "national_id": national_id,
            "enrollment_id": enroll_id, "images_used": len(blobs), "consistency": _muzzle_consistency}


@app.post("/muzzle/identify")
async def identify(file: UploadFile = File(...),
                   source: str = Form("app"),
                   threshold: float = Form(0.70)):
    """개체 조회. 유사도가 임계값 미만이면 ID를 부여하지 않고 미확정 보류."""
    blob = await file.read()
    try:
        q = encoder.embed([blob])[0]
    except ValueError as e:
        raise HTTPException(400, str(e))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT c.id, c.national_id, 1 - (e.embedding <=> %s) AS sim
            FROM public.enrollment e JOIN cattle c ON c.id = e.cattle_id
            WHERE e.is_active
            ORDER BY e.embedding <=> %s
            LIMIT 1
        """, (q, q))
        row = cur.fetchone()

        if row is None:
            cattle_id, national_id, sim = None, None, 0.0
        else:
            cattle_id, national_id, sim = row[0], row[1], float(row[2])

        confirmed = row is not None and sim >= threshold
        decision = "confirmed" if confirmed else "unconfirmed"

        cur.execute("""
            INSERT INTO public.identification_log
              (matched_cattle_id, similarity, threshold_used,
               decision, source, model_version)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (cattle_id if confirmed else None, sim, threshold,
              decision, source, MODEL_VERSION))
        conn.commit()

    return {"cattle_id": cattle_id if confirmed else None,
            "national_id": national_id if confirmed else None,
            "similarity": round(sim, 4),
            "threshold": threshold,
            "decision": decision}

from video_router import router as video_router
app.include_router(video_router, prefix="/muzzle")
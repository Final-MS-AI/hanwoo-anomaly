#!/bin/bash
set -e
cd ~/muzzle_api
mkdir -p test

# --- 1) 합성 이미지 생성 ---------------------------------
./venv/bin/python << 'PYEOF'
import numpy as np, cv2, os
rng = np.random.default_rng(42)
os.makedirs("test", exist_ok=True)

def make(seed, n, tag):
    """같은 seed = 같은 '개체'. 밝기/각도만 살짝 바꿔 여러 장 생성."""
    r = np.random.default_rng(seed)
    base = r.integers(0, 255, (300, 300), dtype=np.uint8)
    base = cv2.GaussianBlur(base, (7, 7), 0)          # 주름 비슷한 질감
    for i in range(n):
        img = base.astype(np.float32)
        img = img * r.uniform(0.85, 1.15) + r.uniform(-15, 15)   # 조명 변화
        M = cv2.getRotationMatrix2D((150, 150), r.uniform(-6, 6), 1.0)
        img = cv2.warpAffine(img.clip(0, 255).astype(np.uint8), M, (300, 300))
        cv2.imwrite(f"test/{tag}_{i}.jpg", cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))

make(1, 3, "cowA")   # 개체 A 3장
make(999, 2, "cowB") # 개체 B 2장
print("합성 이미지 5장 생성 완료")
PYEOF

echo ""
echo "===== 1. 헬스체크 ====="
curl -s localhost:8001/muzzle/health; echo

echo ""
echo "===== 2. 개체 A 등록 (2장) ====="
curl -s -X POST localhost:8001/muzzle/enroll \
  -F "national_id=999900000001" \
  -F "files=@test/cowA_0.jpg" -F "files=@test/cowA_1.jpg"; echo

echo ""
echo "===== 3. 개체 B 등록 (2장) ====="
curl -s -X POST localhost:8001/muzzle/enroll \
  -F "national_id=999900000002" \
  -F "files=@test/cowB_0.jpg" -F "files=@test/cowB_1.jpg"; echo

echo ""
echo "===== 4. A의 미등록 사진으로 조회 → A가 나와야 정상 ====="
curl -s -X POST localhost:8001/muzzle/identify -F "file=@test/cowA_2.jpg"; echo

echo ""
echo "===== 5. B 사진으로 조회 → B가 나와야 정상 ====="
curl -s -X POST localhost:8001/muzzle/identify -F "file=@test/cowB_1.jpg"; echo

echo ""
echo "===== 6. 식별 로그 확인 ====="
./venv/bin/python << 'PYEOF'
import os, psycopg
from dotenv import load_dotenv
load_dotenv("/home/azureuser/muzzle_api/.env")
with psycopg.connect(os.getenv("DATABASE_URL")) as c, c.cursor() as cur:
    cur.execute("""SELECT id, matched_cattle_id, round(similarity::numeric,4),
                          decision, created_at
                   FROM public.identification_log
                   ORDER BY id DESC LIMIT 5""")
    for r in cur.fetchall():
        print(" ", r)
PYEOF

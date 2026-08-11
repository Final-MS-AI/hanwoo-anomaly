# 비문 개체 식별 (Muzzle Identification)

한우 비문(코무늬)으로 개체를 식별하는 서비스. EfficientNet-B0 + ArcFace, 512차원 임베딩, pgvector 코사인 유사도 검색.

## 구성

| 경로 | 내용 |
|---|---|
| `api/` | FastAPI 서비스 (포트 8001) |
| `video/` | 영상 → 개체 확정 파이프라인, 평가 스크립트 |
| `crop/` | YOLO-World 크롭 (정면 근접 정지사진 전용) |
| `train/` | 학습 노트북 (Colab) |
| `weights/` | ONNX 인코더 + PyTorch 체크포인트 |
| `deploy/` | systemd 유닛, Caddy 라우팅 발췌 |
| `docs/` | 모델 카드, API·DB·배포 기록 |
| `results/` | 평가 결과 |
| `THRESHOLD_POLICY.md` | 운영 임계값 근거 |

## 실행

```bash
cd muzzle/api
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env      # DATABASE_URL 채울 것
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001
```

`encoder_onnx.py` 가 `../weights/muzzle_encoder.onnx` 를 참조한다. 경로가 다르면 수정할 것.

## 엔드포인트

| 경로 | 기능 |
|---|---|
| `GET /muzzle/health` | 상태 |
| `POST /muzzle/enroll` | 등록 (`national_id`, `barn_id`, `files[]`) |
| `POST /muzzle/identify` | 식별 (`file`, `threshold`) |
| `GET /muzzle/videos` | ROI 등록된 영상 목록 |
| `POST /muzzle/videos/{name}/identify` | 영상 개체 확정 |

Caddy가 `/muzzle` 접두어를 **제거하지 않는다.** 라우트에 접두어를 포함할 것.

## 다른 파트 주의사항

1. `public.enrollment` / `public.identification_log` 를 직접 SELECT 하지 말 것. 임계값 판정과 보류 로직이 API 계층에만 있어, 직접 조회하면 확신도와 무관하게 항상 최근접 개체가 반환된다.
2. `decision == "unconfirmed"` 이면 **ID를 부여하지 말 것.**
3. 입력은 **코 크롭 이미지**여야 한다. 원본에서 코를 찾는 것은 검출 파트 역할.
4. 개체 집계 시 `WHERE status = 'active'`.
5. `pkill -f uvicorn` 금지 — 8000·8001이 함께 죽는다. 포트를 명시할 것.

## 알려진 한계

- 실촬영 영상 자동 코 검출률 **0%** (YOLO-World zero-shot). 현재는 수동 ROI + 템플릿 추적으로 대체.
- 운영 임계값 0.70은 실영상 도메인 기준. in-domain(0.45)과 다르며 도메인을 넘지 못한다.
- 한우 자체 데이터 검증 미수행 (공개 데이터셋 부재).

## 저장소에 없는 것

| 대상 | 조치 |
|---|---|
| `weights/clip/ViT-B-32.pt` (338MB) | open_clip 공개 가중치. 최초 실행 시 자동 다운로드 |
| 영상 원본(mp4), 크롭 이미지 | 용량·출처 문제로 제외 |
| `.env` | `api/.env.example` 참고해 `DATABASE_URL` 작성 |
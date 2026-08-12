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
| `tracking/` | 영상 추적 추출·적재 스크립트 |
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

가중치 경로는 환경변수로 지정한다. 미지정 시 `/home/azureuser/models/muzzle/weights/muzzle_encoder.onnx` 를 사용한다.

```bash
export MUZZLE_ONNX_PATH=/path/to/muzzle_encoder.onnx
```

> **주의 — 운영 중 가중치 파일을 이동하지 말 것.** `muzzle-api.service` 가 이 파일을 직접 읽는다. 다른 서버로 가져갈 때는 이동(`mv`)이 아니라 복사(`cp`)할 것.

### 다른 서버로 이전할 때

가중치만 옮길 수 없다. API 프로세스가 자기 디스크에서 파일을 읽으므로 서비스 전체가 함께 가야 한다.

| # | 대상 | 비고 |
|---|---|---|
| 1 | `muzzle/api/` 코드 | 저장소에 있음 |
| 2 | `muzzle/weights/muzzle_encoder.onnx` | 저장소에 있음 |
| 3 | `.env` (`DATABASE_URL`) | 저장소에 없음. 직접 작성 |
| 4 | venv | `pip install -r requirements.txt` 로 새로 생성 |
| 5 | systemd 유닛 | `muzzle/deploy/muzzle-api.service` — 경로 수정 필요 |
| 6 | Caddy 라우팅 | `127.0.0.1:8001` → 대상 서버 사설 IP |
| 7 | Azure NSG | 서버 간 8001 포트 허용 |
| 8 | PostgreSQL 방화벽 | 대상 서버 IP 를 `cow-db` 허용 목록에 추가 |

6~8 이 누락되면 코드와 파일을 모두 옮겨도 서비스가 뜨지 않는다.

## 엔드포인트

| 경로 | 기능 |
|---|---|
| `GET /muzzle/health` | 상태 |
| `POST /muzzle/enroll` | 등록 (`national_id`, `barn_id`, `files[]`) |
| `POST /muzzle/identify` | 식별 (`file`, `threshold`) |
| `GET /muzzle/videos` | ROI 등록된 영상 목록 |
| `POST /muzzle/videos/{name}/identify` | 영상 개체 확정 |
| `GET /muzzle/tracks` | 트랙 목록 (`bound=false` 로 미확정만) |
| `GET /muzzle/tracks/{id}` | 트랙 + 현재 바인딩 |
| `POST /muzzle/tracks/{id}/bind` | 트랙에 개체 바인딩 |
| `DELETE /muzzle/tracks/{id}/bind` | 바인딩 해제 |

Caddy가 `/muzzle` 접두어를 **제거하지 않는다.** 라우트에 접두어를 포함할 것.

## 다른 파트 주의사항

1. `public.enrollment` / `public.identification_log` 를 직접 SELECT 하지 말 것. 임계값 판정과 보류 로직이 API 계층에만 있어, 직접 조회하면 확신도와 무관하게 항상 최근접 개체가 반환된다.
2. `decision == "unconfirmed"` 이면 **ID를 부여하지 말 것.**
3. 입력은 **코 크롭 이미지**여야 한다. 원본에서 코를 찾는 것은 검출 파트 역할.
4. 개체 집계 시 `WHERE status = 'active'`.
5. `pkill -f uvicorn` 금지 — 8000·8001이 함께 죽는다. 포트를 명시할 것.
6. 트랙에 개체를 붙일 때는 `POST /muzzle/tracks/{segment_id}/bind` 를 쓸 것. `track_identity_binding` 에 직접 INSERT 하면 임계값 검사와 충돌 규칙을 건너뛴다.
7. `decision` 이 `unconfirmed` 면 바인딩을 호출하지 말 것. 유사도 0.70 미만은 API 가 422 로 거부한다.
8. 개체별 시계열은 `v_identified_track_observation` 뷰를 조회할 것. `track_observation` 을 직접 보면 개체번호가 없다.

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
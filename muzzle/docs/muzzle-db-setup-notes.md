# 비문(코무늬) 식별 — DB 스키마 구축 완료 보고

**작업일** 2026-07-31
**담당** 개체 식별 파트
**대상 리소스** Azure Database for PostgreSQL — `cow-db` (리소스 그룹 `10ai-final-team3`)
**결과** 테이블 3개 생성 완료 · pgvector 활성화 · 동작 검증 완료

---

## 1. 왜 이 작업이 필요했나

비문 식별 모델(EfficientNet-B0 + ArcFace)은 **사진 한 장을 512개의 숫자(임베딩)로 바꿔주는 역할만** 한다. 모델 자체에는 기억이 없다. "이 코가 몇 번 소인지"는 모델이 모른다.

그래서 다음 두 가지가 반드시 DB에 저장되어야 한다.

| 필요한 것 | 이유 |
|---|---|
| 등록된 소들의 임베딩 | 새로 찍은 사진과 비교할 대상이 있어야 "누구인지" 판정 가능 |
| 식별 시도 기록 | 임계값이 적절했는지 사후 검증하고 튜닝하기 위한 근거 데이터 |

즉 **DB 테이블이 없으면 모델은 숫자만 뱉고 끝난다.** 이번 작업이 그 저장소를 만든 것이다.

### 동작 흐름

```
[등록]  코 사진 → 모델 → 임베딩(512차원) → muzzle.enrollment 에 저장
                                              ↑ 소 한 마리당 여러 장 등록 가능

[식별]  코 사진 → 모델 → 임베딩 → enrollment 전체와 코사인 유사도 비교
                                  → 가장 유사한 개체 선택
                                  → 유사도 ≥ 0.40 이면 "확정"
                                  → 미만이면 "미확정" 보류
                                  → 결과를 identification_log 에 기록
```

---

## 2. 무엇을 만들었나

### 2.1 `public.cattle` — 개체 마스터 (공용)

소 한 마리당 한 행. **다른 파트의 테이블도 이 `id`를 FK로 참조하면 된다.**

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGSERIAL PK | 내부 식별자 |
| `national_id` | VARCHAR(12) UNIQUE | 가축이력번호 (12자리) |
| `barn_id` | VARCHAR(50) | 축사·구역 |
| `status` | VARCHAR(20) | 기본값 `active` |
| `created_at` | TIMESTAMPTZ | 등록 시각 |

> 이 테이블만 `public` 스키마에 둔 이유: 시계열·이벤트·알림 등 여러 파트가 공통으로 참조할 개체 명부이기 때문이다. 비문 전용 테이블은 아래처럼 별도 스키마로 격리했다.

### 2.2 `muzzle.enrollment` — 등록된 비문 임베딩

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `cattle_id` | BIGINT FK → `cattle.id` | `ON DELETE CASCADE` |
| `embedding` | **vector(512)** | 모델 출력 임베딩 |
| `image_path` | TEXT | 원본 이미지 위치 (Blob 등) |
| `quality_score` | REAL | 촬영 품질 점수 |
| `captured_at` | TIMESTAMPTZ | 촬영 시각 |
| `is_active` | BOOLEAN | 폐기된 등록 제외용 |
| `created_at` | TIMESTAMPTZ | |

**512는 모델 설정값(`embed_dim = 512`)과 정확히 일치시킨 것이다.** 모델을 바꿔 임베딩 차원이 달라지면 이 컬럼도 함께 변경해야 한다.

선행연구 방식대로 **한 개체를 여러 시점에 나눠 촬영해 여러 행으로 등록**할 수 있게 설계했다(과적합·조건 편향 방지).

### 2.3 `muzzle.identification_log` — 식별 시도 기록

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `query_image_path` | TEXT | 조회에 쓴 이미지 |
| `matched_cattle_id` | BIGINT FK (NULL 허용) | **NULL = 미확정** |
| `similarity` | REAL | 최고 유사도 |
| `threshold_used` | REAL | 판정에 쓴 임계값 |
| `decision` | VARCHAR(20) | `confirmed` / `unconfirmed` |
| `source` | VARCHAR(30) | `app_enroll`, `camera_b` 등 |
| `model_version` | VARCHAR(50) | 모델 버전 |
| `created_at` | TIMESTAMPTZ | |

**성공한 식별뿐 아니라 미확정 건도 전부 남긴다.** 이게 이 테이블의 핵심이다. 나중에 "임계값 0.40이 적절했는가"를 실제 분포로 검증할 수 있고, 발표 자료의 정량 근거가 된다.

---

## 3. 어떻게 진행했나

| 단계 | 내용 |
|---|---|
| 1 | Azure 포털 → `cow-db` → 서버 매개 변수 → `azure.extensions` 에 **VECTOR** 허용 |
| 2 | 네트워킹 → 방화벽 규칙에 접속 지점 IP 등록 (Azure 서비스 허용도 활성) |
| 3 | Cloud Shell(Bash)에서 `schema_muzzle.sql` 작성 |
| 4 | `psql -f schema_muzzle.sql` 실행 → 테이블·인덱스 생성 |
| 5 | 더미 벡터 삽입 → `vector_dims = 512`, 자기유사도 `= 1` 확인 → 테스트 데이터 삭제 |
| 6 | VM에 `db/schema_muzzle.sql` 로 스키마 파일 보관 |

### 검증 결과

```
 dims | self_sim
------+----------
  512 |        1
```

벡터 타입 저장과 코사인 거리 연산(`<=>`)이 정상 작동함을 확인했다.

---

## 4. 다른 파트가 알아야 할 것 ★

### 4.1 개체 참조는 `public.cattle.id`로

소를 참조하는 테이블(시계열 지표, 이상 이벤트, 조치 기록 등)은 개체번호 문자열을 직접 들고 있지 말고 **`cattle(id)`를 FK로 참조**해주세요. 가축이력번호는 `cattle.national_id`에 있습니다.

### 4.2 비문 식별은 SQL 직접 조회 금지 — API로 호출

`muzzle.enrollment`를 직접 SELECT 해서 유사도를 계산하지 말아주세요. 아래 두 엔드포인트를 통해 호출해주시면 됩니다. (식별 파트에서 제공 예정)

| 엔드포인트 | 용도 |
|---|---|
| `POST /muzzle/enroll` | 개체 등록 — 이미지 + 가축이력번호 → 임베딩 생성·저장 |
| `POST /muzzle/identify` | 개체 식별 — 이미지 → `{cattle_id, similarity, decision}` 반환 |

**이유:** 임계값 판정(0.40)과 **미확정 보류 로직**이 API 안에 들어가야 합니다. 밖에서 직접 쿼리하면 "저신뢰도는 강제로 ID를 부여하지 않는다"는 설계 원칙이 우회되어, 개체 오배정으로 baseline이 오염될 수 있습니다.

`decision` 값 처리 규칙:

- `confirmed` → 해당 `cattle_id`로 기록
- `unconfirmed` → **ID를 부여하지 말고 보류.** 소는 급이대·음수대를 하루에 여러 번 방문하므로 다음 방문에서 재확정할 기회가 반복해서 옵니다.

### 4.3 전처리 조건 고정

모델은 다음 조건으로 학습되었습니다. **추론 시에도 동일하게 맞춰야** 성능이 유지됩니다.

- 그레이스케일 변환 (`GRAY = True`)
- CLAHE 대비 보정 (`CLAHE = True`)
- 입력 크기 224×224
- 임베딩 512차원, ArcFace (`s=30.0`, `m=0.3`)

> 그레이스케일은 데이터셋 문제를 피하려는 임시방편이 아니라, **모델이 코 주름 대신 털색을 학습하는 지름길(shortcut)을 차단하기 위한 설계**입니다. 한우는 단색이라 특히 중요합니다.

---

## 5. 파일 위치

| 항목 | 위치 |
|---|---|
| 스키마 DDL | VM: `db/schema_muzzle.sql` |
| 비문 모델 | VM: `models/` |
| DB 서버 | `cow-db.postgres.database.azure.com` (포트 5432, `sslmode=require` 필수) |

접속 시 참고:

```bash
psql "host=cow-db.postgres.database.azure.com port=5432 dbname=postgres \
      user=<사용자명> sslmode=require"
```

> 접속이 timeout 되면 방화벽에 본인 IP가 등록되지 않은 경우입니다. 포털 → `cow-db` → 네트워킹 → 방화벽 규칙에서 **현재 클라이언트 IP 주소 추가** 후 저장하세요.

---

## 6. 다음 작업

- [ ] `POST /muzzle/enroll`, `POST /muzzle/identify` API 구현 (식별 파트)
- [ ] 임베딩 정규화 방식을 학습 시점과 일치시켜 고정
- [ ] 등록 데이터가 쌓인 뒤 `ivfflat` 벡터 인덱스 추가 (현 규모에서는 순차 검색으로 충분)
- [ ] `identification_log` 누적 후 임계값 재검토

---

## 부록 · 용어

| 용어 | 뜻 |
|---|---|
| **임베딩** | 이미지를 숫자 배열로 압축한 것. 같은 개체면 비슷한 배열이 나온다 |
| **pgvector** | PostgreSQL에서 벡터를 저장하고 유사도 검색을 하게 해주는 확장 기능 |
| **코사인 유사도** | 두 벡터가 얼마나 같은 방향인지. 1에 가까울수록 동일 개체 |
| **임계값 0.40** | 이 값 이상이면 동일 개체로 확정. 검증 결과 오배정률 0.000 |
| **미확정 보류** | 확신이 낮으면 ID를 붙이지 않고 넘기는 것. 잘못 붙이면 두 개체의 baseline이 동시에 오염되기 때문 |
| **스키마** | DB 안의 폴더 같은 것. `muzzle` 스키마로 비문 관련 테이블을 격리했다 |

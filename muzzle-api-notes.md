
---

## 16. 트랙·시계열 인계 규칙 (2026-08-12 추가)

### 16.1 개체별 시계열은 API 로 받을 것

엔드포인트: `GET /muzzle/cattle/{national_id}/timeline`
질의 파라미터: `start`, `end` (ISO8601), `limit` (기본 2000), `include_test` (기본 false)

응답은 두 층이다. 필요한 해상도만 쓰면 된다.

| 필드 | 내용 |
|---|---|
| `segments` | 트랙 단위 요약 — 시작·종료 시각, 관측 수, 유사도 |
| `observations` | 프레임 단위 원시 데이터 — `ts`, `bbox`, `conf`, `behavior` |

**`v_identified_track_observation` 뷰를 직접 조회하지 말 것.** 이유는 둘이다.

1. **테스트 데이터가 섞인다.** 검증용 데이터는 삭제하지 않고 `session_id` 를
   `test_` 로 시작시켜 격리한다. 필터는 뷰가 아니라 이 엔드포인트에 있다
   (뷰는 팀 공용이므로 내 사정으로 필터를 걸지 않았다).
2. **바인딩의 소급 적용을 놓칠 수 있다.** 개체번호는 관측 행에 기록되지 않고
   `track_identity_binding` 1행이 JOIN 으로 소급 적용한다. 직접 짠 쿼리가 이
   JOIN 을 빠뜨리면 식별 이전 구간이 통째로 비어 보인다.

### 16.2 트랙 테이블 소유권

| 테이블 | 소유 | 비고 |
|---|---|---|
| `track_segment` | 개체 식별 파트 | 카메라·세션·트랙 단위 구간 |
| `track_observation` | 개체 식별 파트 | 프레임 단위. `behavior` 는 이상행동 파이프라인이 채운다 |
| `track_identity_binding` | 개체 식별 파트 | **역전파의 핵심.** 트랙당 활성 바인딩 1행 |
| `v_identified_track_observation` | 개체 식별 파트 | 위 3개를 JOIN 한 조회용 뷰 |

`track_` 접두어는 전부 개체 식별 파트 소유다. INSERT/UPDATE 가 필요하면 API 로
요청할 것. 특히 `track_identity_binding` 에 직접 INSERT 하면 임계값 검사·중복
방지·이력 보존이 모두 우회된다.

### 16.3 세션 ID 접두어 규약

- `test_20260812023011-e3eca6` — 검증용. timeline 기본 응답에서 제외
- `demo_...` — 발표용. 노출
- `20260812023011-e3eca6` — 실데이터. 노출

검증 데이터는 **삭제하지 않고 남긴다.** 지우면 재현에 매번 추론을 다시 돌려야
하고, 발표 시 "그때 그 결과"를 보여줄 수 없다. `is_test` 컬럼을 새로 만들지
않은 것은 팀 공용 DB 에서 `ALTER TABLE` 을 피하기 위해서다 — `session_id` 는
이미 "추적 1회 실행 단위"라는 의미를 갖고 있어 규약과 어긋나지 않는다.

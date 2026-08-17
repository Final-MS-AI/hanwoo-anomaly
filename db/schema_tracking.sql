-- 추적 · 개체 바인딩 스키마
-- 신규 테이블만 생성한다. 기존 테이블은 변경하지 않는다.
-- 팀 컨벤션(단일 public 스키마)에 따라 track_ 접두어로 구분한다.

-- 한 카메라에서 한 물체가 연속으로 보인 구간
CREATE TABLE IF NOT EXISTS public.track_segment (
  id           BIGSERIAL PRIMARY KEY,
  camera_id    TEXT        NOT NULL,
  session_id   TEXT        NOT NULL,   -- 추적 프로그램 1회 실행 단위
  track_id     INT         NOT NULL,   -- 추적기가 준 임시 번호
  started_at   TIMESTAMPTZ NOT NULL,
  ended_at     TIMESTAMPTZ,
  frame_count  INT         NOT NULL DEFAULT 0,
  source_video TEXT,
  UNIQUE (camera_id, session_id, track_id)
);

-- 프레임 단위 관측
CREATE TABLE IF NOT EXISTS public.track_observation (
  id         BIGSERIAL PRIMARY KEY,
  segment_id BIGINT      NOT NULL REFERENCES public.track_segment(id) ON DELETE CASCADE,
  ts         TIMESTAMPTZ NOT NULL,
  frame_idx  INT,
  bbox_x REAL, bbox_y REAL, bbox_w REAL, bbox_h REAL,
  conf   REAL,
  -- 이상행동 파트 파이프라인(behavior_extract.py)에서만 채워진다.
  -- 비문 전용 추적(track_extract.py)으로 들어온 행은 NULL 이다.
  behavior      TEXT,
  behavior_conf REAL
);
CREATE INDEX IF NOT EXISTS idx_track_obs_segment_ts
  ON public.track_observation (segment_id, ts);

-- ★ 역전파의 핵심. 한 행이 그 트랙의 과거 관측 전체에 소급 적용된다
CREATE TABLE IF NOT EXISTS public.track_identity_binding (
  id          BIGSERIAL PRIMARY KEY,
  segment_id  BIGINT      NOT NULL REFERENCES public.track_segment(id) ON DELETE CASCADE,
  cattle_id   BIGINT      REFERENCES public.cattle(id),   -- cattle.id 가 bigint
  national_id VARCHAR     NOT NULL,
  source      TEXT        NOT NULL,   -- 'muzzle' | 'eartag'
  similarity  REAL,
  decided_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_active   BOOLEAN     NOT NULL DEFAULT TRUE
);

-- 한 트랙에 유효한 바인딩은 하나뿐. 충돌을 DB가 거부한다
CREATE UNIQUE INDEX IF NOT EXISTS uq_track_binding_active
  ON public.track_identity_binding (segment_id) WHERE is_active;

-- 조회용 뷰 — 여기를 보면 과거·미래가 전부 개체번호를 갖는다
CREATE OR REPLACE VIEW public.v_identified_track_observation AS
SELECT o.id, o.ts, o.frame_idx, o.bbox_x, o.bbox_y, o.bbox_w, o.bbox_h, o.conf,
       s.camera_id, s.track_id, s.session_id, s.id AS segment_id,
       b.cattle_id, b.national_id, b.source, b.similarity,
       -- 새 컬럼은 반드시 맨 뒤. CREATE OR REPLACE VIEW 는 컬럼 추가만
       -- 허용하며 중간 삽입은 기존 컬럼의 이름 변경으로 해석돼 거부된다.
       o.behavior, o.behavior_conf
FROM       public.track_observation      o
JOIN       public.track_segment          s ON s.id = o.segment_id
LEFT JOIN  public.track_identity_binding b ON b.segment_id = s.id AND b.is_active;
-- ── 2026-08-18 추가 ────────────────────────────────────────────────
-- 같은 session_id 로 track_load.py 를 두 번 실행하면 관측 행이 조용히
-- 두 배가 되는 사고가 있었다 (demo_20260814070456-136a18, 2832행 중복).
-- track_segment 에는 UNIQUE 가 있어 세그먼트는 중복되지 않았고
-- frame_count 도 정상값을 유지했으므로 눈으로는 탐지되지 않았다.
--
-- 유일 인덱스로 DB 가 거부하게 하고, track_load.py 는 ON CONFLICT
-- DO NOTHING 으로 예외 없이 넘긴다. 재적재가 멱등이 된다.
--
-- 주의: Postgres 는 NULL 을 서로 다른 값으로 취급하므로 frame_idx 가
-- NULL 인 행은 이 인덱스로 막히지 않는다. track_load.py 는 항상 값을
-- 채우므로 현재 문제되지 않으나 알려진 범위로 기록한다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_track_obs_segment_frame
  ON public.track_observation (segment_id, frame_idx);

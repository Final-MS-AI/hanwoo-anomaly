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
  conf   REAL
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
       b.cattle_id, b.national_id, b.source, b.similarity
FROM       public.track_observation      o
JOIN       public.track_segment          s ON s.id = o.segment_id
LEFT JOIN  public.track_identity_binding b ON b.segment_id = s.id AND b.is_active;
-- 초크포인트 구역 스키마 (2026-08-17)
-- 신규 테이블만 생성한다. 기존 테이블은 변경하지 않는다.
-- 팀 컨벤션(단일 public 스키마)에 따라 track_ 접두어로 구분한다.
--
-- 좌표는 정규화(0~1)로 저장하고 frame_w/h 를 함께 둔다. 카메라 해상도가
-- 달라져도 같은 다각형이 유효하다. bbox 는 픽셀이므로 판정 시 변환한다.

CREATE TABLE IF NOT EXISTS public.track_zone (
  id          BIGSERIAL   PRIMARY KEY,
  name        TEXT        NOT NULL,
  -- cowow_devices(device_id) 와 대응하나 FK 는 걸지 않는다.
  -- 기기 스키마는 다른 파트 소유이며 확정 전이다. 확정되면 그때 건다.
  device_id   TEXT,
  camera_id   TEXT        NOT NULL DEFAULT 'A',
  frame_w     INT         NOT NULL,
  frame_h     INT         NOT NULL,
  -- [[x, y], ...] 정규화 꼭짓점. 3개 이상은 API 계층에서 검사한다.
  poly        JSONB       NOT NULL,
  -- bbox 의 어느 점으로 구역 진입을 판정하는가. 실측 기본값 topright
  anchor      TEXT        NOT NULL DEFAULT 'topright',
  -- 재지정 시 삭제하지 않고 비활성화한다. 이력 보존 + 되돌리기
  is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 같은 기기·카메라·이름으로 활성 구역은 하나뿐. 충돌을 DB 가 거부한다.
-- device_id 가 NULL 인 행끼리도 비교되도록 COALESCE 로 감싼다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_track_zone_active
  ON public.track_zone (COALESCE(device_id, ''), camera_id, name)
  WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_track_zone_lookup
  ON public.track_zone (name, camera_id)
  WHERE is_active;

-- 현재 zones.py 에 하드코딩된 'top' 구역을 그대로 이관한다.
-- 이 행이 있어야 DB 전환 후에도 기존 시연 명령이 동일하게 동작한다.
INSERT INTO public.track_zone (name, device_id, camera_id, frame_w, frame_h, poly, anchor)
SELECT 'top', NULL, 'A', 1920, 1080,
       '[[0.0009,0.7023],[0.0009,0.7487],[0.1226,0.6034],[0.3026,0.452],
         [0.4939,0.3067],[0.6243,0.2124],[0.6122,0.2],[0.4565,0.3051],
         [0.3009,0.4241],[0.16,0.5354]]'::jsonb,
       'topright'
WHERE NOT EXISTS (
  SELECT 1 FROM public.track_zone
  WHERE name = 'top' AND camera_id = 'A' AND device_id IS NULL AND is_active
);
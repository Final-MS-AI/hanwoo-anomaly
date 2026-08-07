-- 한우 비문 식별 DB 스키마 (Azure DB for PostgreSQL: cow-db)
-- 적용 완료: 2026-07-31
-- embed_dim = 512 (EfficientNet-B0 + ArcFace, gray + CLAHE, img 224)

CREATE EXTENSION IF NOT EXISTS vector;

-- 개체 마스터 (공용 — 시계열·이벤트 테이블도 이 id를 FK로 참조)
CREATE TABLE IF NOT EXISTS cattle (
    id           BIGSERIAL PRIMARY KEY,
    national_id  VARCHAR(12) UNIQUE NOT NULL,   -- 가축이력번호
    barn_id      VARCHAR(50),
    status       VARCHAR(20) DEFAULT 'active',
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE SCHEMA IF NOT EXISTS muzzle;

-- 등록된 비문 임베딩
CREATE TABLE IF NOT EXISTS muzzle.enrollment (
    id             BIGSERIAL PRIMARY KEY,
    cattle_id      BIGINT NOT NULL REFERENCES cattle(id) ON DELETE CASCADE,
    embedding      vector(512) NOT NULL,
    image_path     TEXT,
    quality_score  REAL,
    captured_at    TIMESTAMPTZ,
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_enroll_cattle ON muzzle.enrollment(cattle_id);

-- 식별 시도 기록 (미확정 보류 건도 전부 남긴다 — 임계값 튜닝 근거)
CREATE TABLE IF NOT EXISTS muzzle.identification_log (
    id                BIGSERIAL PRIMARY KEY,
    query_image_path  TEXT,
    matched_cattle_id BIGINT REFERENCES cattle(id),   -- NULL = 미확정
    similarity        REAL,
    threshold_used    REAL NOT NULL,
    decision          VARCHAR(20) NOT NULL,           -- confirmed | unconfirmed
    source            VARCHAR(30),
    model_version     VARCHAR(50),
    created_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_idlog_cattle_time
    ON muzzle.identification_log(matched_cattle_id, created_at DESC);
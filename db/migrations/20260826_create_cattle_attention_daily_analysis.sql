-- COWOW left-panel daily attention analysis
-- Independent from the team's existing anomaly_events / behavior_* pipeline.
-- This migration creates only a new table and indexes.

CREATE TABLE IF NOT EXISTS public.cattle_attention_daily_analysis (
    id BIGSERIAL PRIMARY KEY,
    cattle_id BIGINT NOT NULL REFERENCES public.cattle(id) ON DELETE CASCADE,
    analysis_date DATE NOT NULL,

    -- computed: 실제 track/behavior 집계 결과
    -- demo_simulated: 장기 CCTV 부재를 보완하기 위한 시연용 일별 결과
    source TEXT NOT NULL DEFAULT 'computed'
        CHECK (source IN ('computed', 'demo_simulated')),

    status TEXT NOT NULL
        CHECK (status IN (
            'normal',
            'warning',
            'insufficient_data',
            'insufficient_baseline'
        )),

    -- warning 발생 시 대표 원인. normal/insufficient에서는 NULL 가능.
    primary_metric TEXT,
    primary_change_ratio DOUBLE PRECISION,
    warning_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 오늘 관측/행동 원본값과 파생 비율.
    valid_observation_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
    feed_bunk_duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
    feed_bunk_ratio DOUBLE PRECISION,
    lying_duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
    lying_ratio DOUBLE PRECISION,
    standing_duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
    standing_ratio DOUBLE PRECISION,
    walking_duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
    walking_ratio DOUBLE PRECISION,

    -- 개인 baseline: 직전 10개 유효 관찰일 평균.
    baseline_valid_days INTEGER NOT NULL DEFAULT 0,
    baseline_required_days INTEGER NOT NULL DEFAULT 10,
    baseline_feed_bunk_ratio DOUBLE PRECISION,
    baseline_lying_ratio DOUBLE PRECISION,
    baseline_standing_ratio DOUBLE PRECISION,
    baseline_walking_ratio DOUBLE PRECISION,

    -- (오늘 - baseline) / baseline. -0.18 = 18% 감소.
    feed_bunk_change_ratio DOUBLE PRECISION,
    lying_change_ratio DOUBLE PRECISION,
    standing_change_ratio DOUBLE PRECISION,
    walking_change_ratio DOUBLE PRECISION,

    streak_days INTEGER NOT NULL DEFAULT 0,
    data_quality_reason TEXT,
    model_version TEXT NOT NULL DEFAULT 'cowow-attention-v1',

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (cattle_id, analysis_date, source, model_version)
);

CREATE INDEX IF NOT EXISTS idx_cattle_attention_daily_cattle_date
    ON public.cattle_attention_daily_analysis (cattle_id, analysis_date DESC);

CREATE INDEX IF NOT EXISTS idx_cattle_attention_daily_status_date
    ON public.cattle_attention_daily_analysis (status, analysis_date DESC);

COMMENT ON TABLE public.cattle_attention_daily_analysis IS
'COWOW 왼쪽 대시보드 전용 일별 주의 분석 결과. 기존 behavior_* / anomaly_events와 독립.';

COMMENT ON COLUMN public.cattle_attention_daily_analysis.feed_bunk_change_ratio IS
'개인 직전 10개 유효일 급이대 체류비율 평균 대비 변화율. COWOW 주의 기준은 -0.18 이하.';

COMMENT ON COLUMN public.cattle_attention_daily_analysis.lying_change_ratio IS
'개인 직전 10개 유효일 누움비율 평균 대비 변화율. COWOW 주의 기준은 -0.30 이하.';

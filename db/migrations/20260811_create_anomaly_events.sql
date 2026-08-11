-- Dashboard anomaly event storage
-- The production database table was created manually before this migration
-- was added to source control.

CREATE TABLE IF NOT EXISTS public.anomaly_events (
    id BIGSERIAL PRIMARY KEY,
    cattle_id BIGINT NOT NULL REFERENCES public.cattle(id),
    anomaly_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL
        CHECK (severity IN ('warning', 'danger')),
    score DOUBLE PRECISION
        CHECK (
            score IS NULL
            OR (score >= 0.0 AND score <= 1.0)
        ),
    message TEXT NOT NULL,
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    model_version VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomaly_events_cattle_id
    ON public.anomaly_events(cattle_id);

CREATE INDEX IF NOT EXISTS idx_anomaly_events_detected_at
    ON public.anomaly_events(detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_anomaly_events_active
    ON public.anomaly_events(cattle_id, severity)
    WHERE is_active = true;

BEGIN;

ALTER TABLE public.model_feedback
    ADD COLUMN IF NOT EXISTS anomaly_event_id varchar(128),
    ADD COLUMN IF NOT EXISTS event_source varchar(32),
    ADD COLUMN IF NOT EXISTS device_id varchar(100),
    ADD COLUMN IF NOT EXISTS triage_stage varchar(32),
    ADD COLUMN IF NOT EXISTS evidence_blob_name text,
    ADD COLUMN IF NOT EXISTS feedback_fingerprint varchar(128),
    ADD COLUMN IF NOT EXISTS weekly_batch_id uuid;

CREATE INDEX IF NOT EXISTS idx_model_feedback_anomaly_event
    ON public.model_feedback (anomaly_event_id);

CREATE INDEX IF NOT EXISTS idx_model_feedback_weekly_batch
    ON public.model_feedback (weekly_batch_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_model_feedback_fingerprint
    ON public.model_feedback (feedback_fingerprint)
    WHERE feedback_fingerprint IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.feedback_weekly_runs (
    id uuid PRIMARY KEY,
    period_started_at timestamptz NOT NULL,
    period_ended_at timestamptz NOT NULL,
    status varchar(24) NOT NULL,
    collected_count integer NOT NULL DEFAULT 0,
    approved_count integer NOT NULL DEFAULT 0,
    policy_feedback_count integer NOT NULL DEFAULT 0,
    behavior_feedback_count integer NOT NULL DEFAULT 0,
    detection_feedback_count integer NOT NULL DEFAULT 0,
    tracking_feedback_count integer NOT NULL DEFAULT 0,
    manifest_blob_name text,
    policy_before jsonb,
    policy_after jsonb,
    candidate_model_path text,
    evaluation_metrics jsonb,
    promoted_at timestamptz,
    failure_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_feedback_weekly_runs_created
    ON public.feedback_weekly_runs (created_at DESC);

COMMIT;

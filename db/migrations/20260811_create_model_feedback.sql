BEGIN;

CREATE TABLE IF NOT EXISTS public.model_feedback (
    id uuid PRIMARY KEY,
    user_id bigint REFERENCES public.users(id) ON DELETE SET NULL,
    job_id varchar(128) NOT NULL,
    feedback_type varchar(32) NOT NULL,
    frame_time_seconds double precision NOT NULL DEFAULT 0,
    track_id varchar(128),
    predicted_label varchar(100),
    corrected_label varchar(100),
    comment varchar(1000),
    source_video_url text,
    result_video_url text,
    evidence_path text,
    inference_summary jsonb,
    review_status varchar(20) NOT NULL DEFAULT 'pending',
    reviewer_note text,
    reviewed_at timestamptz,
    training_exported_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT model_feedback_type_check CHECK (
        feedback_type IN (
            'missed_cow',
            'false_detection',
            'wrong_tracking',
            'wrong_behavior',
            'false_anomaly',
            'missed_anomaly'
        )
    ),
    CONSTRAINT model_feedback_review_status_check CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'exported')
    ),
    CONSTRAINT model_feedback_time_check CHECK (frame_time_seconds >= 0)
);

CREATE INDEX IF NOT EXISTS idx_model_feedback_review_status_created
    ON public.model_feedback (review_status, created_at);

CREATE INDEX IF NOT EXISTS idx_model_feedback_job_id
    ON public.model_feedback (job_id);

CREATE INDEX IF NOT EXISTS idx_model_feedback_user_created
    ON public.model_feedback (user_id, created_at DESC);

COMMIT;


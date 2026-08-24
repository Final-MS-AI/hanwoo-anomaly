CREATE TABLE IF NOT EXISTS public.track_feedback_reviews (
    id BIGSERIAL PRIMARY KEY,
    segment_id BIGINT NOT NULL REFERENCES public.track_segment(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('approved', 'held')),
    reviewer_user_id BIGINT REFERENCES public.users(id),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (segment_id)
);

CREATE INDEX IF NOT EXISTS idx_track_feedback_reviews_reviewed_at
    ON public.track_feedback_reviews (reviewed_at DESC);

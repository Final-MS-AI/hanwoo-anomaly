CREATE TABLE IF NOT EXISTS public.ear_tag_ocr_results (
    id bigserial PRIMARY KEY,
    request_id varchar(64) NOT NULL UNIQUE,
    cattle_id bigint,
    detected_ear_tag_number varchar(9),
    confidence double precision DEFAULT 0.0 NOT NULL,
    ocr_status varchar(50) NOT NULL,
    verification varchar(100),
    requires_human_confirmation boolean DEFAULT false NOT NULL,
    vote_count integer DEFAULT 0 NOT NULL,
    evidence_local_path text,
    final_result_path text,
    raw_result jsonb,
    created_at timestamptz DEFAULT now() NOT NULL,

    CONSTRAINT chk_ear_tag_ocr_confidence
        CHECK (confidence >= 0.0 AND confidence <= 1.0),

    CONSTRAINT chk_ear_tag_ocr_number
        CHECK (
            detected_ear_tag_number IS NULL
            OR detected_ear_tag_number ~ '^[0-9]{9}$'
        ),

    CONSTRAINT chk_ear_tag_ocr_vote_count
        CHECK (vote_count >= 0),

    CONSTRAINT ear_tag_ocr_results_cattle_id_fkey
        FOREIGN KEY (cattle_id)
        REFERENCES public.cattle(id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_ear_tag_ocr_results_cattle_id
    ON public.ear_tag_ocr_results (cattle_id);

CREATE INDEX IF NOT EXISTS idx_ear_tag_ocr_results_created_at
    ON public.ear_tag_ocr_results (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ear_tag_ocr_results_detected_number
    ON public.ear_tag_ocr_results (detected_ear_tag_number);

-- 관리자 권한을 환경 변수 목록이 아닌 DB에서 관리한다.
CREATE TABLE IF NOT EXISTS public.admin_users (
    user_id BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    granted_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_users_granted_at
    ON public.admin_users (granted_at DESC);

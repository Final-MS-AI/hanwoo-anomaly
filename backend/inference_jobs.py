from __future__ import annotations

import threading
from typing import Any


_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def create_job(job_id: str, input_path: str) -> None:
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "영상 업로드 완료",
            "input_path": input_path,
            "result_url": None,
            "summary": None,
            "error": None,
        }


def update_job(job_id: str, **values: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(values)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None

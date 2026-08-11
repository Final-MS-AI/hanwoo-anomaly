from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth_session import COOKIE_NAME, read_user_id
from feedback_evidence import capture_feedback_frame
from feedback_repository import create_feedback, list_user_feedback
from inference_jobs import get_job


FeedbackType = Literal[
    "missed_cow",
    "false_detection",
    "wrong_tracking",
    "wrong_behavior",
    "false_anomaly",
    "missed_anomaly",
]


class FeedbackCreate(BaseModel):
    job_id: str = Field(min_length=1, max_length=128)
    feedback_type: FeedbackType
    frame_time_seconds: float = Field(default=0, ge=0, le=86400)
    track_id: str | None = Field(default=None, max_length=128)
    predicted_label: str | None = Field(default=None, max_length=100)
    corrected_label: str | None = Field(default=None, max_length=100)
    comment: str | None = Field(default=None, max_length=1000)
    source_video_url: str | None = Field(default=None, max_length=2048)
    result_video_url: str | None = Field(default=None, max_length=2048)
    inference_summary: dict[str, Any] | None = None

    @field_validator("track_id", "predicted_label", "corrected_label", "comment")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


router = APIRouter(prefix="/feedback", tags=["Model feedback"])


@router.post("", status_code=201)
def submit_feedback(
    payload: FeedbackCreate,
    cowow_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    user_id = read_user_id(cowow_session)
    feedback_id = str(uuid.uuid4())
    job = get_job(payload.job_id)

    evidence_path = capture_feedback_frame(
        job.get("input_path") if job else None,
        payload.frame_time_seconds,
        feedback_id,
    )

    summary = payload.inference_summary
    if summary is None and job:
        summary = job.get("summary")

    try:
        created = create_feedback(
            {
                "id": feedback_id,
                "user_id": user_id,
                "job_id": payload.job_id,
                "feedback_type": payload.feedback_type,
                "frame_time_seconds": payload.frame_time_seconds,
                "track_id": payload.track_id,
                "predicted_label": payload.predicted_label,
                "corrected_label": payload.corrected_label,
                "comment": payload.comment,
                "source_video_url": payload.source_video_url,
                "result_video_url": payload.result_video_url,
                "evidence_path": evidence_path,
                "inference_summary": summary,
            }
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="피드백을 저장하지 못했습니다.",
        ) from exc

    created["evidence_available"] = bool(evidence_path)
    return created


@router.get("/mine")
def read_my_feedback(
    limit: int = Query(default=50, ge=1, le=100),
    cowow_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    user_id = read_user_id(cowow_session)
    try:
        return {"items": list_user_feedback(user_id, limit=limit)}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="피드백 목록을 불러오지 못했습니다.",
        ) from exc


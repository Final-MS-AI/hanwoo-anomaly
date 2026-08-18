from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth_session import COOKIE_NAME, read_user_id
from feedback_evidence import capture_feedback_frame
from feedback_repository import (
    create_feedback,
    list_user_feedback,
    resolve_feedback_context,
)
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
    anomaly_event_id: str | None = Field(default=None, max_length=128)

    @field_validator("track_id", "predicted_label", "corrected_label", "comment")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


router = APIRouter(prefix="/feedback", tags=["Model feedback"])

TRIAGE_STAGE = {
    "false_anomaly": "anomaly_policy",
    "missed_anomaly": "anomaly_policy",
    "wrong_behavior": "behavior_classifier",
    "false_detection": "cow_detector",
    "missed_cow": "cow_detector",
    "wrong_tracking": "identity_tracking",
}


@router.post("", status_code=201)
def submit_feedback(
    payload: FeedbackCreate,
    cowow_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    user_id = read_user_id(cowow_session)
    feedback_id = str(uuid.uuid4())
    job = get_job(payload.job_id)
    context = resolve_feedback_context(user_id, payload.anomaly_event_id)
    if payload.anomaly_event_id and context is None:
        raise HTTPException(
            status_code=404,
            detail="접근할 수 있는 원본 이상 이벤트를 찾지 못했습니다.",
        )

    predicted_label = payload.predicted_label
    if context and context.get("predicted_label"):
        predicted_label = str(context["predicted_label"])

    corrected_label = payload.corrected_label
    if payload.feedback_type == "false_anomaly" and not corrected_label:
        corrected_label = "normal"
    if payload.feedback_type == "wrong_behavior" and not corrected_label:
        raise HTTPException(
            status_code=422,
            detail="실제 행동을 선택해 주세요.",
        )

    fingerprint_source = "|".join(
        (
            str(user_id),
            payload.anomaly_event_id or payload.job_id,
            payload.feedback_type,
            corrected_label or "",
        )
    )
    feedback_fingerprint = hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()

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
                "predicted_label": predicted_label,
                "corrected_label": corrected_label,
                "comment": payload.comment,
                "source_video_url": payload.source_video_url,
                "result_video_url": payload.result_video_url,
                "evidence_path": evidence_path,
                "inference_summary": summary,
                "anomaly_event_id": payload.anomaly_event_id,
                "event_source": context.get("event_source") if context else "upload_job",
                "device_id": context.get("device_id") if context else None,
                "triage_stage": TRIAGE_STAGE[payload.feedback_type],
                "evidence_blob_name": (
                    context.get("evidence_blob_name") if context else None
                ),
                "feedback_fingerprint": feedback_fingerprint,
            }
        )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="이미 같은 판단에 대한 피드백을 보냈습니다.",
        ) from exc
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


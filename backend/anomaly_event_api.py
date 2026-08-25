from __future__ import annotations

import hmac
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)
from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, UploadFile

from auth_session import read_user_id


router = APIRouter(tags=["Anomaly events"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "")
    if not value:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured.")
    return value


def storage_client() -> tuple[BlobServiceClient, str]:
    account_url = os.getenv(
        "AZURE_STORAGE_ACCOUNT_URL",
        "https://cowimage.blob.core.windows.net",
    )
    container_name = os.getenv("AZURE_ANOMALY_BLOB_CONTAINER", "anomaly-media")
    if not account_url:
        raise HTTPException(
            status_code=503,
            detail="Azure Blob Storage is not configured.",
        )
    return (
        BlobServiceClient(
            account_url=account_url,
            credential=DefaultAzureCredential(),
        ),
        container_name,
    )


def ensure_schema() -> None:
    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS edge_devices (
                    edge_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL
                        REFERENCES cowow_devices(device_id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL,
                    secret_hash TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS camera_devices (
                    camera_id TEXT PRIMARY KEY,
                    edge_id TEXT NOT NULL
                        REFERENCES edge_devices(edge_id) ON DELETE CASCADE,
                    device_id TEXT NOT NULL
                        REFERENCES cowow_devices(device_id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS device_anomaly_events (
                    id UUID PRIMARY KEY,
                    device_id TEXT NOT NULL
                        REFERENCES cowow_devices(device_id) ON DELETE CASCADE,
                    camera_id TEXT NOT NULL,
                    cattle_id TEXT,
                    status TEXT NOT NULL CHECK (status IN ('warning', 'danger')),
                    behavior TEXT NOT NULL,
                    confidence DOUBLE PRECISION,
                    detected_at TIMESTAMPTZ NOT NULL,
                    analysis_session_id TEXT,
                    image_blob_name TEXT,
                    video_blob_name TEXT,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_device_anomaly_events_active
                ON device_anomaly_events(device_id, resolved_at, detected_at DESC)
                """
            )
        connection.commit()


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_demo_edge() -> None:
    edge_id = os.getenv("COWOW_EDGE_ID", "EDGE-DEMO-01").strip()
    edge_secret = os.getenv("COWOW_EDGE_SECRET", "")
    device_id = os.getenv("ESP32_PHYSICAL_DEVICE_ID", "ESP32-01").strip()
    if not edge_secret:
        return

    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM cowow_devices WHERE device_id=%s", (device_id,))
            if not cursor.fetchone():
                return
            cursor.execute(
                """
                INSERT INTO edge_devices (
                    edge_id, device_id, display_name, secret_hash
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (edge_id) DO NOTHING
                """,
                (edge_id, device_id, "시연용 로컬 분석 서버", secret_hash(edge_secret)),
            )
        connection.commit()


def verify_edge(edge_id: str | None, edge_secret: str | None) -> str:
    if not edge_id or not edge_secret:
        raise HTTPException(status_code=401, detail="Edge credentials are required.")
    ensure_demo_edge()
    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT device_id, secret_hash
                FROM edge_devices
                WHERE edge_id=%s AND enabled=TRUE
                """,
                (edge_id.strip(),),
            )
            row = cursor.fetchone()
            if not row or not hmac.compare_digest(row[1], secret_hash(edge_secret)):
                raise HTTPException(status_code=401, detail="Invalid edge credentials.")
            cursor.execute(
                "UPDATE edge_devices SET last_seen_at=NOW() WHERE edge_id=%s",
                (edge_id.strip(),),
            )
        connection.commit()
    return row[0]


def bind_camera(camera_id: str, edge_id: str, device_id: str) -> None:
    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT edge_id, device_id FROM camera_devices WHERE camera_id=%s",
                (camera_id,),
            )
            existing = cursor.fetchone()
            if existing and existing != (edge_id, device_id):
                raise HTTPException(
                    status_code=409,
                    detail="Camera is already bound to another installation.",
                )
            cursor.execute(
                """
                INSERT INTO camera_devices (
                    camera_id, edge_id, device_id, display_name, last_seen_at
                )
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (camera_id) DO UPDATE SET last_seen_at=NOW()
                """,
                (camera_id, edge_id, device_id, "시연용 영상 입력"),
            )
        connection.commit()


def require_edge_configuration() -> None:
    if not os.getenv("COWOW_EDGE_SECRET", ""):
        raise HTTPException(
            status_code=503,
            detail="COWOW_EDGE_SECRET is not configured.",
        )


def validate_upload(upload: UploadFile | None, kind: str) -> None:
    if upload is None:
        return
    allowed = ALLOWED_IMAGE_TYPES if kind == "image" else ALLOWED_VIDEO_TYPES
    maximum = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
    if upload.content_type not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported {kind} content type.")
    if upload.size is not None and upload.size > maximum:
        raise HTTPException(status_code=413, detail=f"{kind.title()} file is too large.")


def upload_media(
    upload: UploadFile | None,
    *,
    event_id: uuid.UUID,
    device_id: str,
    kind: str,
) -> str | None:
    if upload is None:
        return None

    service, container_name = storage_client()
    container = service.get_container_client(container_name)
    try:
        container.create_container()
    except ResourceExistsError:
        pass

    suffix = Path(upload.filename or "").suffix.lower()
    if not suffix:
        suffix = ".jpg" if kind == "image" else ".mp4"

    now = datetime.now(timezone.utc)
    safe_device_id = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in device_id
    )
    blob_name = (
        f"events/{safe_device_id}/{now:%Y/%m/%d}/"
        f"{event_id}/{kind}{suffix}"
    )
    upload.file.seek(0)
    container.get_blob_client(blob_name).upload_blob(
        upload.file,
        overwrite=True,
        content_settings=ContentSettings(
            content_type=upload.content_type,
            cache_control="private, no-store",
        ),
    )
    return blob_name


def read_url(blob_name: str | None) -> str | None:
    if not blob_name:
        return None
    service, container_name = storage_client()
    starts_on = datetime.now(timezone.utc) - timedelta(minutes=5)
    expires_on = datetime.now(timezone.utc) + timedelta(minutes=15)
    delegation_key = service.get_user_delegation_key(
        key_start_time=starts_on,
        key_expiry_time=expires_on,
    )
    token = generate_blob_sas(
        account_name=service.account_name,
        container_name=container_name,
        blob_name=blob_name,
        user_delegation_key=delegation_key,
        permission=BlobSasPermissions(read=True),
        start=starts_on,
        expiry=expires_on,
    )
    blob = service.get_blob_client(container=container_name, blob=blob_name)
    return f"{blob.url}?{token}"


def parse_detected_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="detectedAt must be ISO 8601.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@router.post("/inference/events", status_code=201)
def create_anomaly_event(
    cameraId: str = Form(min_length=1, max_length=100),
    status: str = Form(),
    behavior: str = Form(min_length=1, max_length=300),
    cattleId: str | None = Form(default=None, max_length=100),
    trackId: str | None = Form(default=None, max_length=100),
    confidence: float | None = Form(default=None, ge=0, le=1),
    detectedAt: str | None = Form(default=None),
    sessionId: str | None = Form(default=None, max_length=200),
    image: UploadFile | None = File(default=None),
    video: UploadFile | None = File(default=None),
    x_edge_id: str | None = Header(default=None),
    x_edge_secret: str | None = Header(default=None),
):
    require_edge_configuration()
    normalized_status = status.strip().lower()
    if normalized_status not in {"warning", "danger"}:
        raise HTTPException(status_code=422, detail="status must be warning or danger.")
    validate_upload(image, "image")
    validate_upload(video, "video")
    ensure_schema()
    device_id = verify_edge(x_edge_id, x_edge_secret)
    camera_id = cameraId.strip()
    bind_camera(camera_id, x_edge_id.strip(), device_id)

    event_id = uuid.uuid4()
    image_blob_name = upload_media(
        image,
        event_id=event_id,
        device_id=device_id,
        kind="image",
    )
    video_blob_name = upload_media(
        video,
        event_id=event_id,
        device_id=device_id,
        kind="video",
    )

    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO device_anomaly_events (
                    id, device_id, camera_id, cattle_id, status, behavior,
                    confidence, detected_at, analysis_session_id,
                    image_blob_name, video_blob_name, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id,
                    device_id,
                    camera_id,
                    cattleId.strip() if cattleId else None,
                    normalized_status,
                    behavior.strip(),
                    confidence,
                    parse_detected_at(detectedAt),
                    sessionId.strip() if sessionId else None,
                    image_blob_name,
                    video_blob_name,
                    psycopg.types.json.Jsonb(
                        {"trackId": trackId.strip()} if trackId else {}
                    ),
                ),
            )
        connection.commit()

    return {
        "eventId": str(event_id),
        "deviceId": device_id,
        "edgeId": x_edge_id.strip(),
        "cameraId": camera_id,
        "status": normalized_status,
        "saved": True,
    }


@router.get("/anomalies/active")
def active_anomalies(cowow_session: str | None = Cookie(default=None)):
    user_id = read_user_id(cowow_session)
    ensure_schema()

    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT provider FROM users WHERE id=%s", (user_id,))
            user_row = cursor.fetchone()
            if not user_row:
                raise HTTPException(status_code=401, detail="User was not found.")

            cursor.execute(
                """
                SELECT e.id, e.device_id, e.camera_id, e.cattle_id,
                       e.status, e.behavior, e.confidence, e.detected_at,
                       e.analysis_session_id, e.image_blob_name,
                       e.video_blob_name
                FROM device_anomaly_events e
                WHERE e.resolved_at IS NULL
                  AND (
                    EXISTS (
                        SELECT 1 FROM device_owners o
                        WHERE o.device_id=e.device_id AND o.user_id=%s
                    )
                    OR EXISTS (
                        SELECT 1 FROM device_members m
                        WHERE m.device_id=e.device_id AND m.user_id=%s
                    )
                    OR (
                        %s = 'guest'
                        AND e.device_id = %s
                        AND NOT EXISTS (
                            SELECT 1 FROM device_owners o2
                            WHERE o2.device_id=e.device_id
                        )
                    )
                  )
                ORDER BY e.detected_at DESC
                LIMIT 100
                """,
                (
                    user_id,
                    user_id,
                    user_row[0],
                    os.getenv("ESP32_PHYSICAL_DEVICE_ID", "ESP32-01"),
                ),
            )
            rows = cursor.fetchall()

    data = []
    for row in rows:
        detected_at = row[7]
        data.append(
            {
                "id": str(row[0]),
                "deviceId": row[1],
                "cameraId": row[2],
                "cattleId": row[3] or "미확인 개체",
                "status": row[4],
                "behavior": row[5],
                "confidence": row[6],
                "detectedAt": detected_at.isoformat(),
                "lastDetectedAt": detected_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                "time": detected_at.astimezone().strftime("%H:%M"),
                "sessionId": row[8],
                "imageUrl": read_url(row[9]),
                "videoUrl": read_url(row[10]),
            }
        )

    unique_cattle = {item["cattleId"] for item in data}
    return {
        "data": data,
        "count": len(data),
        "summary": {
            "total": len(unique_cattle),
            "normal": 0,
            "warning": len({
                item["cattleId"] for item in data if item["status"] == "warning"
            }),
            "danger": len({
                item["cattleId"] for item in data if item["status"] == "danger"
            }),
        },
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)


CONNECTION_STRING = os.getenv(
    "AZURE_STORAGE_CONNECTION_STRING",
    "",
)

CONTAINER_NAME = os.getenv(
    "AZURE_BLOB_CONTAINER",
    "images",
)


def get_blob_service_client() -> BlobServiceClient:
    if not CONNECTION_STRING:
        raise RuntimeError(
            "AZURE_STORAGE_CONNECTION_STRING이 설정되지 않았습니다."
        )

    return BlobServiceClient.from_connection_string(
        CONNECTION_STRING
    )


def upload_result_video(
    local_path: Path,
    job_id: str,
) -> str:
    if not local_path.exists():
        raise FileNotFoundError(
            f"업로드할 결과 영상이 없습니다: {local_path}"
        )

    service_client = get_blob_service_client()

    container_client = service_client.get_container_client(
        CONTAINER_NAME
    )

    try:
        container_client.create_container()
    except Exception:
        # 이미 존재하는 컨테이너라면 그대로 사용합니다.
        pass

    now = datetime.now(timezone.utc)

    blob_name = (
        f"inference-results/"
        f"{now:%Y/%m/%d}/"
        f"{job_id}_result.mp4"
    )

    blob_client = container_client.get_blob_client(
        blob_name
    )

    with local_path.open("rb") as video_file:
        blob_client.upload_blob(
            video_file,
            overwrite=True,
            content_settings=ContentSettings(
                content_type="video/mp4",
                cache_control="no-cache",
            ),
        )

    account_name = service_client.account_name
    credential = service_client.credential

    account_key = getattr(
        credential,
        "account_key",
        None,
    )

    if not account_key:
        raise RuntimeError(
            "SAS 생성을 위한 Storage Account Key를 "
            "연결 문자열에서 찾지 못했습니다."
        )

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=now + timedelta(hours=24),
    )

    return f"{blob_client.url}?{sas_token}"

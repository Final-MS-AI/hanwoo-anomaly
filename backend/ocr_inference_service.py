from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from inference_jobs import update_job


# ---------------------------------------------------------
# OCR 파이프라인 경로
# ---------------------------------------------------------

OCR_PROJECT_DIR = Path("/home/azureuser/models/ocr")
OCR_SCRIPT_PATH = (
    OCR_PROJECT_DIR
    / "scripts"
    / "23_run_eartag_pipeline.py"
)

OCR_IMAGE_SCRIPT_PATH = (
    OCR_PROJECT_DIR
    / "scripts"
    / "26_register_eartag_image.py"
)

OCR_EARTAG_MODEL_PATH = (
    OCR_PROJECT_DIR
    / "models"
    / "eartag_yolov8n_2451_960.pt"
)

# FastAPI 작업별 OCR 결과 저장 위치
BASE_DIR = Path(__file__).resolve().parent
OCR_RESULT_ROOT = BASE_DIR / "ocr_results"

OCR_RESULT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


# ---------------------------------------------------------
# 최종 결과 파일 검색
# ---------------------------------------------------------

def find_final_result(output_dir: Path) -> Path:
    """
    OCR 파이프라인 출력 폴더에서 final_result.json을 찾습니다.

    파이프라인이 입력 영상 이름으로 하위 폴더를 만들 수도 있으므로
    하위 디렉터리까지 재귀적으로 검색합니다.
    """
    direct_result = output_dir / "final_result.json"

    if direct_result.exists():
        return direct_result

    candidates = list(
        output_dir.rglob("final_result.json")
    )

    if not candidates:
        raise FileNotFoundError(
            "OCR 실행은 종료됐지만 final_result.json을 "
            f"찾지 못했습니다: {output_dir}"
        )

    # 여러 파일이 발견되면 가장 최근에 수정된 결과를 선택
    return max(
        candidates,
        key=lambda path: path.stat().st_mtime,
    )


# ---------------------------------------------------------
# OCR 결과 JSON 읽기
# ---------------------------------------------------------

def load_final_result(
    result_path: Path,
) -> dict[str, Any]:
    try:
        with result_path.open(
            "r",
            encoding="utf-8",
        ) as result_file:
            result = json.load(result_file)

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"final_result.json 형식이 올바르지 않습니다: "
            f"{result_path}"
        ) from exc

    if not isinstance(result, dict):
        raise RuntimeError(
            "final_result.json의 최상위 데이터가 "
            "JSON 객체가 아닙니다."
        )

    return result


# ---------------------------------------------------------
# OCR 비동기 백그라운드 작업
# ---------------------------------------------------------

def process_ocr_job(
    job_id: str,
    input_path: str,
    camera_id: str,
) -> None:
    """
    FastAPI BackgroundTasks에서 실행되는 OCR 작업입니다.

    1. 작업 상태를 processing으로 변경
    2. OCR 파이프라인을 별도 프로세스로 실행
    3. final_result.json 읽기
    4. 작업 결과 저장
    """
    input_video = Path(input_path)
    job_output_dir = OCR_RESULT_ROOT / job_id
    log_path = job_output_dir / "pipeline.log"

    try:
        update_job(
            job_id,
            status="processing",
            progress=5,
            message="OCR 파이프라인 준비 중",
        )

        if not input_video.exists():
            raise FileNotFoundError(
                f"업로드 영상이 없습니다: {input_video}"
            )

        if not OCR_SCRIPT_PATH.exists():
            raise FileNotFoundError(
                f"OCR 실행 파일이 없습니다: "
                f"{OCR_SCRIPT_PATH}"
            )

        job_output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = [
            # 현재 FastAPI 가상환경의 Python 사용
            sys.executable,
            str(OCR_SCRIPT_PATH),
            "--source",
            str(input_video),
            "--output",
            str(job_output_dir),
            "--camera-id",
            camera_id,
            "--timezone",
            "Asia/Seoul",
        ]

        update_job(
            job_id,
            status="processing",
            progress=10,
            message="귀표 검출 및 추적 시작",
            output_dir=str(job_output_dir),
            log_path=str(log_path),
        )

        # stdout과 stderr를 작업별 로그 파일로 저장
        with log_path.open(
            "w",
            encoding="utf-8",
        ) as log_file:
            completed_process = subprocess.run(
                command,
                cwd=str(OCR_PROJECT_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=1800,  # 최대 30분
                check=False,
            )

        if completed_process.returncode != 0:
            raise RuntimeError(
                "OCR 파이프라인 실행에 실패했습니다. "
                f"종료 코드: {completed_process.returncode}, "
                f"로그: {log_path}"
            )

        update_job(
            job_id,
            status="processing",
            progress=95,
            message="OCR 결과 정리 중",
        )

        final_result_path = find_final_result(
            job_output_dir
        )
        final_result = load_final_result(
            final_result_path
        )

        pipeline_status = final_result.get(
            "pipeline_status"
        )
        result_status = final_result.get("status")

        if pipeline_status != "completed":
            raise RuntimeError(
                "OCR 파이프라인이 정상 완료 상태가 아닙니다. "
                f"pipeline_status={pipeline_status}"
            )

        allowed_result_statuses = {
            "success",
            "not_found",
        }

        if result_status not in allowed_result_statuses:
            raise RuntimeError(
                "OCR 결과 상태가 정상 완료 상태가 아닙니다. "
                f"status={result_status}"
            )

        update_job(
            job_id,
            status="completed",
            progress=100,
            message="귀표 OCR 분석 완료",
            summary=final_result,
            final_result_path=str(final_result_path),
            identity_count=final_result.get(
                "identity_count",
                0,
            ),
            error=None,
        )

    except subprocess.TimeoutExpired:
        update_job(
            job_id,
            status="failed",
            progress=0,
            message="OCR 분석 시간 초과",
            error="OCR 파이프라인이 30분 안에 완료되지 않았습니다.",
            log_path=str(log_path),
        )

    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            progress=0,
            message="귀표 OCR 분석 실패",
            error=str(exc),
            log_path=str(log_path),
        )


# ---------------------------------------------------------
# 소 등록용 귀표 사진 OCR
# ---------------------------------------------------------

def _find_value_recursive(
    value: Any,
    candidate_keys: set[str],
) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in candidate_keys and item not in (
                None,
                "",
            ):
                return item

        for item in value.values():
            found = _find_value_recursive(
                item,
                candidate_keys,
            )

            if found not in (None, ""):
                return found

    if isinstance(value, list):
        for item in value:
            found = _find_value_recursive(
                item,
                candidate_keys,
            )

            if found not in (None, ""):
                return found

    return None


def extract_ear_tag_result(
    final_result: dict[str, Any],
) -> dict[str, Any]:
    tag_keys = {
        "ear_tag_number",
        "eartag_number",
        "ear_tag",
        "eartag",
        "tag_number",
        "tag_id",
        "identity",
        "recognized_text",
        "ocr_text",
        "text",
    }

    confidence_keys = {
        "ocr_confidence",
        "confidence",
        "score",
        "recognition_score",
    }

    raw_tag = _find_value_recursive(
        final_result,
        tag_keys,
    )

    confidence = _find_value_recursive(
        final_result,
        confidence_keys,
    )

    if raw_tag is None:
        raise RuntimeError(
            "OCR는 완료됐지만 귀표 번호를 결과에서 찾지 못했습니다."
        )

    ear_tag_number = str(raw_tag).strip()

    if not ear_tag_number:
        raise RuntimeError(
            "인식된 귀표 번호가 비어 있습니다."
        )

    try:
        confidence_value = (
            float(confidence)
            if confidence is not None
            else None
        )
    except (TypeError, ValueError):
        confidence_value = None

    return {
        "ear_tag_number": ear_tag_number,
        "confidence": confidence_value,
        "raw_result": final_result,
    }


def process_ocr_image(
    image_path: str,
    request_id: str,
    camera_id: str = "registration_camera",
) -> dict[str, Any]:
    input_image = Path(image_path)
    job_output_dir = OCR_RESULT_ROOT / f"image-{request_id}"
    temporary_video = job_output_dir / "input_image.mp4"
    log_path = job_output_dir / "pipeline.log"

    if not input_image.exists():
        raise FileNotFoundError(
            f"귀표 사진이 없습니다: {input_image}"
        )

    if not OCR_SCRIPT_PATH.exists():
        raise FileNotFoundError(
            f"OCR 실행 파일이 없습니다: {OCR_SCRIPT_PATH}"
        )

    job_output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # 기존 영상 OCR 파이프라인을 재사용하기 위해
    # 사진 한 장을 짧은 MP4 영상으로 변환합니다.
    ffmpeg_command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(input_image),
        "-t",
        "2",
        "-r",
        "5",
        "-vf",
        (
            "scale="
            "trunc(iw/2)*2:"
            "trunc(ih/2)*2"
        ),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(temporary_video),
    ]

    ffmpeg_process = subprocess.run(
        ffmpeg_command,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    if ffmpeg_process.returncode != 0:
        raise RuntimeError(
            "귀표 사진의 영상 변환에 실패했습니다: "
            + ffmpeg_process.stderr[-2000:]
        )

    command = [
        sys.executable,
        str(OCR_SCRIPT_PATH),
        "--source",
        str(temporary_video),
        "--output",
        str(job_output_dir),
        "--camera-id",
        camera_id,
        "--timezone",
        "Asia/Seoul",
    ]

    with log_path.open(
        "w",
        encoding="utf-8",
    ) as log_file:
        completed_process = subprocess.run(
            command,
            cwd=str(OCR_PROJECT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
            check=False,
        )

    if completed_process.returncode != 0:
        raise RuntimeError(
            "귀표 사진 OCR 실행에 실패했습니다. "
            f"종료 코드={completed_process.returncode}, "
            f"로그={log_path}"
        )

    final_result_path = find_final_result(
        job_output_dir
    )

    final_result = load_final_result(
        final_result_path
    )

    result = extract_ear_tag_result(
        final_result
    )

    result["request_id"] = request_id
    result["final_result_path"] = str(
        final_result_path
    )

    return result


# ---------------------------------------------------------
# 소 등록용 귀표 사진 OCR
# ---------------------------------------------------------

def _find_value_recursive(
    value: Any,
    candidate_keys: set[str],
) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in candidate_keys and item not in (
                None,
                "",
            ):
                return item

        for item in value.values():
            found = _find_value_recursive(
                item,
                candidate_keys,
            )

            if found not in (None, ""):
                return found

    if isinstance(value, list):
        for item in value:
            found = _find_value_recursive(
                item,
                candidate_keys,
            )

            if found not in (None, ""):
                return found

    return None


def extract_ear_tag_result(
    final_result: dict[str, Any],
) -> dict[str, Any]:
    tag_keys = {
        "ear_tag_number",
        "eartag_number",
        "ear_tag",
        "eartag",
        "tag_number",
        "tag_id",
        "identity",
        "recognized_text",
        "ocr_text",
        "text",
    }

    confidence_keys = {
        "ocr_confidence",
        "confidence",
        "score",
        "recognition_score",
    }

    raw_tag = _find_value_recursive(
        final_result,
        tag_keys,
    )

    confidence = _find_value_recursive(
        final_result,
        confidence_keys,
    )

    if raw_tag is None:
        raise RuntimeError(
            "OCR는 완료됐지만 귀표 번호를 결과에서 찾지 못했습니다."
        )

    ear_tag_number = str(raw_tag).strip()

    if not ear_tag_number:
        raise RuntimeError(
            "인식된 귀표 번호가 비어 있습니다."
        )

    try:
        confidence_value = (
            float(confidence)
            if confidence is not None
            else None
        )
    except (TypeError, ValueError):
        confidence_value = None

    return {
        "ear_tag_number": ear_tag_number,
        "confidence": confidence_value,
        "raw_result": final_result,
    }


def process_ocr_image(
    image_path: str,
    request_id: str,
    camera_id: str = "registration_camera",
) -> dict[str, Any]:
    """원본 사진에서 귀표를 검출·Crop하고 OCR 번호를 판독합니다."""
    input_image = Path(image_path)
    job_output_dir = OCR_RESULT_ROOT / f"image-{request_id}"
    log_path = job_output_dir / "pipeline.log"

    if not input_image.is_file():
        raise FileNotFoundError(
            f"귀표 사진이 없습니다: {input_image}"
        )

    if not OCR_IMAGE_SCRIPT_PATH.is_file():
        raise FileNotFoundError(
            "사진 OCR 실행 파일이 없습니다: "
            f"{OCR_IMAGE_SCRIPT_PATH}"
        )

    if not OCR_EARTAG_MODEL_PATH.is_file():
        raise FileNotFoundError(
            "귀표 검출 모델이 없습니다: "
            f"{OCR_EARTAG_MODEL_PATH}"
        )

    job_output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        sys.executable,
        str(OCR_IMAGE_SCRIPT_PATH),
        "--source",
        str(input_image),
        "--input-mode",
        "full-image",
        "--model",
        str(OCR_EARTAG_MODEL_PATH),
        "--output",
        str(job_output_dir),
        "--run-id",
        request_id,
        "--padding",
        "0.25",
        "--dev",
    ]

    with log_path.open(
        "w",
        encoding="utf-8",
    ) as log_file:
        completed_process = subprocess.run(
            command,
            cwd=str(OCR_PROJECT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
            check=False,
        )

    if completed_process.returncode != 0:
        raise RuntimeError(
            "귀표 사진 등록 파이프라인 실행에 실패했습니다. "
            f"종료 코드={completed_process.returncode}, "
            f"로그={log_path}"
        )

    final_result_path = find_final_result(
        job_output_dir
    )
    final_result = load_final_result(
        final_result_path
    )

    pipeline_status = final_result.get(
        "pipeline_status"
    )

    if pipeline_status != "completed":
        raise RuntimeError(
            "사진 귀표 파이프라인이 완료되지 않았습니다. "
            f"pipeline_status={pipeline_status}"
        )

    identities = final_result.get("identities") or []

    if not identities:
        detection_count = int(
            final_result.get("detection_count") or 0
        )
        cloud_sent_count = int(
            final_result.get("cloud_sent_count") or 0
        )

        # 사진 한 장에서는 동일 번호 투표 수가 1회라
        # identities에 확정 후보가 들어가지 않을 수 있습니다.
        # 이 경우 registration_details.json의 OCR 결과를 읽어
        # 번호는 사용자에게 보여주되 수동 확인 대상으로 반환합니다.
        details_path = (
            final_result_path.parent
            / "registration_details.json"
        )

        ocr_result_path = (
            final_result_path.parent
            / "ocr"
            / "azure_eartag_read_results.json"
        )

        candidates: list[dict[str, Any]] = []

        # 개발 모드에서는 registration_details.json을 우선 사용합니다.
        if (
            cloud_sent_count > 0
            and details_path.is_file()
        ):
            try:
                details = json.loads(
                    details_path.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                json.JSONDecodeError,
                OSError,
            ) as exc:
                raise RuntimeError(
                    "등록 상세 결과를 읽지 못했습니다: "
                    f"{details_path}"
                ) from exc

            if isinstance(details, list):
                for row in details:
                    if not isinstance(row, dict):
                        continue

                    ocr_result = row.get("ocr") or {}

                    if isinstance(ocr_result, dict):
                        candidate = dict(ocr_result)
                        candidate["crop"] = row.get("crop")
                        candidates.append(candidate)

        # 운영 모드에서는 registration_details.json이 정리될 수 있으므로
        # Azure OCR 결과 JSON을 fallback으로 사용합니다.
        if (
            cloud_sent_count > 0
            and not candidates
            and ocr_result_path.is_file()
        ):
            try:
                ocr_results = json.loads(
                    ocr_result_path.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                json.JSONDecodeError,
                OSError,
            ) as exc:
                raise RuntimeError(
                    "Azure OCR 결과를 읽지 못했습니다: "
                    f"{ocr_result_path}"
                ) from exc

            if isinstance(ocr_results, list):
                candidates.extend(
                    item
                    for item in ocr_results
                    if isinstance(item, dict)
                )

        normalized_candidates: list[
            dict[str, Any]
        ] = []

        for ocr_result in candidates:
            number = (
                ocr_result.get("cattle_id")
                or ocr_result.get("printed_id")
                or ocr_result.get("candidate_id")
            )

            if not number:
                continue

            try:
                confidence = float(
                    ocr_result.get(
                        "selected_confidence"
                    )
                    or ocr_result.get(
                        "candidate_average_confidence"
                    )
                    or ocr_result.get(
                        "ocr_average_confidence"
                    )
                    or 0.0
                )
            except (
                TypeError,
                ValueError,
            ):
                confidence = 0.0

            try:
                vote_count = int(
                    ocr_result.get("vote_count")
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                vote_count = 0

            normalized_candidates.append(
                {
                    "number": str(number),
                    "confidence": confidence,
                    "vote_count": vote_count,
                    "status": str(
                        ocr_result.get("status")
                        or "unconfirmed"
                    ),
                    "verification": ocr_result.get(
                        "verification"
                    ),
                    "crop": ocr_result.get(
                        "crop"
                    ),
                }
            )

        if normalized_candidates:
            best_candidate = max(
                normalized_candidates,
                key=lambda item: item["confidence"],
            )

            return {
                "success": False,
                "ear_tag_number": best_candidate[
                    "number"
                ],
                "confidence": best_candidate[
                    "confidence"
                ],
                "requires_human_confirmation": True,
                "reason": "single_image_unconfirmed",
                "vote_count": best_candidate[
                    "vote_count"
                ],
                "verification": best_candidate.get(
                    "verification"
                ),
                "evidence_local_path": best_candidate.get(
                    "crop"
                ),
                "request_id": request_id,
                "final_result_path": str(
                    final_result_path
                ),
                "ocr_result_path": str(
                    ocr_result_path
                ),
                "raw_result": final_result,
            }

        if detection_count == 0:
            reason = "ear_tag_not_detected"
        elif cloud_sent_count == 0:
            reason = "crop_quality_rejected"
        else:
            reason = "ear_tag_number_not_found"

        return {
            "success": False,
            "ear_tag_number": None,
            "confidence": 0.0,
            "requires_human_confirmation": False,
            "reason": reason,
            "vote_count": 0,
            "request_id": request_id,
            "final_result_path": str(final_result_path),
            "raw_result": final_result,
        }

    identity = max(
        identities,
        key=lambda item: float(
            item.get("confidence")
            or item.get("selected_confidence")
            or 0.0
        ),
    )

    ear_tag_number = (
        identity.get("cattle_id")
        or identity.get("printed_id")
        or identity.get("identity_id")
    )

    if not ear_tag_number:
        raise RuntimeError(
            "등록 후보는 있지만 귀표 번호 필드가 없습니다."
        )

    confidence = float(
        identity.get("confidence")
        or identity.get("selected_confidence")
        or 0.0
    )

    return {
        "success": True,
        "ear_tag_number": str(ear_tag_number),
        "confidence": confidence,
        "request_id": request_id,
        "final_result_path": str(final_result_path),
        "raw_result": final_result,
    }

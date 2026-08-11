# Ear Tag OCR Backend Integration

## Overview

FastAPI와 PostgreSQL을 이용해 한우 귀표 OCR 결과를
서비스 API와 데이터베이스에 연결하는 백엔드 계층입니다.

## Components

- `ocr_api.py`
  - 귀표 이미지/영상 OCR 요청 API
  - OCR 결과 응답
  - OCR 결과 DB 저장 연동

- `ocr_inference_service.py`
  - FastAPI와 OCR 추론 파이프라인 연결
  - 이미지/영상 OCR 실행
  - OCR 결과 정규화

- `ocr_result_media_api.py`
  - OCR 결과 Bounding Box 이미지 조회
  - OCR evidence crop 조회

- `ear_tag_ocr_repository.py`
  - OCR 결과 PostgreSQL 저장

- `ear_tag_ocr_query_repository.py`
  - OCR 결과 조회

- `inference_jobs.py`
  - OCR 비동기 작업 상태 관리

- `cattle_repository.py`
  - 귀표 번호 기반 등록 개체 조회

## Service Flow

Client
→ FastAPI OCR API
→ OCR inference pipeline
→ OCR result normalization
→ PostgreSQL
→ OCR result/media API
→ React UI

## Human-in-the-loop

OCR 결과가 확정되지 않은 경우
`requires_human_confirmation`과 `verification` 정보를 저장해
사용자 검증 및 수정 흐름에 사용할 수 있도록 구성합니다.

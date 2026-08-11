from __future__ import annotations

from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .rag_answer import (
    RetrievedChunk,
    build_clients,
    generate_answer,
    retrieve,
    rewrite_query,
)


# ---------------------------------------------------------
# RAG 라우터
#
# GET  /rag/health
# POST /rag/chat
# ---------------------------------------------------------

router = APIRouter(
    prefix="/rag",
    tags=["RAG Chat"],
)


# ---------------------------------------------------------
# Azure 클라이언트
# ---------------------------------------------------------

_search_client = None
_embedding_client = None
_response_client = None
_client_lock = Lock()


# ---------------------------------------------------------
# 요청 모델
# ---------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class RagChatRequest(BaseModel):
    question: str = Field(
        min_length=2,
        max_length=1000,
        description="사용자가 입력한 질문",
    )

    messages: list[ChatMessage] = Field(
        default_factory=list,
        description="이전 대화 내역",
    )

    mode: Literal["short", "normal", "detailed"] = Field(
        default="normal",
        description="답변 상세도",
    )


# ---------------------------------------------------------
# 응답 모델
# ---------------------------------------------------------

class RagSource(BaseModel):
    id: str
    title: str
    page: str | None = None


class RagChatResponse(BaseModel):
    answer: str
    sources: list[RagSource]


# ---------------------------------------------------------
# Azure 클라이언트 초기화
# ---------------------------------------------------------

def get_rag_clients():
    global _search_client
    global _embedding_client
    global _response_client

    if (
        _search_client is not None
        and _embedding_client is not None
        and _response_client is not None
    ):
        return (
            _search_client,
            _embedding_client,
            _response_client,
        )

    with _client_lock:
        if (
            _search_client is None
            or _embedding_client is None
            or _response_client is None
        ):
            (
                _search_client,
                _embedding_client,
                _response_client,
            ) = build_clients()

    return (
        _search_client,
        _embedding_client,
        _response_client,
    )


# ---------------------------------------------------------
# 프론트엔드용 출처 변환
# ---------------------------------------------------------

def serialize_sources(
    chunks: list[RetrievedChunk],
) -> list[RagSource]:
    return [
        RagSource(
            id=chunk.id,
            title=chunk.document_title,
            page=chunk.page_label,
        )
        for chunk in chunks
    ]


# ---------------------------------------------------------
# RAG 상태 확인
# GET /rag/health
# ---------------------------------------------------------

@router.get("/health")
def rag_health():
    try:
        get_rag_clients()

        return {
            "status": "healthy",
            "service": "livestock-rag",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"RAG 클라이언트 초기화 실패: {exc}",
        ) from exc


# ---------------------------------------------------------
# RAG 질문
# POST /rag/chat
# ---------------------------------------------------------

@router.post(
    "/chat",
    response_model=RagChatResponse,
)
def rag_chat(
    request: RagChatRequest,
) -> RagChatResponse:
    try:
        (
            search_client,
            embedding_client,
            response_client,
        ) = get_rag_clients()

        # 현재는 마지막 질문만 검색에 사용한다.
        # messages는 프론트 호환을 위해 받지만 아직 사용하지 않는다.
        history = [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in request.messages
        ]

        search_query = rewrite_query(
            query=request.question,
            messages=history,
            response_client=response_client,
        )

        _, chunks = retrieve(
            search_query,
            search_client,
            embedding_client,
            request.mode,
        )

        generated = generate_answer(
            query=request.question,
            chunks=chunks,
            response_client=response_client,
            mode=request.mode,
            messages=history,
            search_query=search_query,
        )

        return RagChatResponse(
            answer=generated.text,
            sources=serialize_sources(
                generated.cited_chunks
            ),
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"RAG 답변 생성 실패: {exc}",
        ) from exc
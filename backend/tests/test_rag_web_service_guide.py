from __future__ import annotations

from types import SimpleNamespace

from rag.rag_answer import (
    RetrievedChunk,
    build_fallback_search_query,
    generate_answer,
    is_web_service_question,
    resolve_cited_sources,
    retrieve,
    retrieve_web_service_guide,
    rewrite_query,
)


class FakeResponses:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=self.output_text,
            status="completed",
            incomplete_details=None,
        )


class FakeClient:
    def __init__(self, output_text: str):
        self.responses = FakeResponses(output_text)


def test_service_guide_chunk_ids_are_converted_to_numeric_citations():
    chunks = [
        RetrievedChunk(
            id=f"cowow-service-guide-{number}",
            document_title="COWOW web service guide",
            document_type="service_guide",
            page_start=None,
            page_end=None,
            section_path="test",
            content="test content",
        )
        for number in range(1, 3)
    ]

    result = resolve_cited_sources(
        answer="Retry with another image[cowow-service-guide-1][cowow-service-guide-2].",
        chunks=chunks,
        max_sources=3,
    )

    assert result.text == "Retry with another image[1][2]."
    assert result.cited_chunks == chunks


def test_web_service_question_detection():
    assert is_web_service_question("귀표 이미지 등록이 실패하면 어떻게 해야 하나요?")
    assert is_web_service_question("영상 분석은 어디에서 시작하나요?")
    assert is_web_service_question("AI 판단이 잘못됐을 때 신고하는 방법은?")
    assert is_web_service_question("주의 개체와 위험 개체의 기준은 무엇인가요?")
    assert not is_web_service_question("구제역 의심축을 발견하면 어떻게 하나요?")


def test_web_service_retrieve_does_not_call_external_clients():
    class UnexpectedClient:
        def __getattr__(self, name):
            raise AssertionError(f"외부 클라이언트를 호출하면 안 됩니다: {name}")

    route, chunks = retrieve(
        "귀표 등록 절차를 알려주세요.",
        search=UnexpectedClient(),
        aoai=UnexpectedClient(),
        mode="short",
    )

    assert route["route"] == "service_guide"
    assert chunks


def test_ear_tag_failure_uses_local_service_guide():
    route, chunks = retrieve_web_service_guide(
        "귀표 이미지 등록이 실패하면 어떻게 해야 하나요?",
        max_chunks=3,
    )

    assert route["route"] == "service_guide"
    assert chunks
    assert chunks[0].document_type == "service_guide"
    assert "귀표 OCR" in chunks[0].section_path
    assert "직접 입력" in chunks[0].content
    assert "같은 `소 등록` 화면" in chunks[0].content
    assert "`귀표 번호` 입력란" in chunks[0].content
    assert "직접 첨부할 수 없습니다" in chunks[0].content
    assert "오류 메시지나 오류 코드를 텍스트로 입력" in chunks[0].content


def test_video_analysis_question_selects_video_section():
    _, chunks = retrieve_web_service_guide(
        "웹에서 영상 분석은 어떻게 시작하나요?",
        max_chunks=2,
    )

    assert chunks
    assert "영상 분석" in chunks[0].section_path
    assert "영상 분석 시작" in chunks[0].content


def test_service_guide_does_not_claim_frontend_thresholds():
    _, chunks = retrieve_web_service_guide(
        "주의 개체와 위험 개체의 기준이 무엇인가요?",
        max_chunks=2,
    )

    joined = "\n".join(chunk.content for chunk in chunks)
    assert "정확한 수치 기준은 프론트 코드에 정의되어 있지 않습니다" in joined


def test_service_guide_answer_is_concise_and_cleans_broken_format(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    _, chunks = retrieve_web_service_guide(
        "귀표 이미지 등록이 실패하면 어떻게 해야 하나요?",
        max_chunks=3,
    )
    client = FakeClient(
        "선명한 사진으로 다시 시도하거나 귀표 번호를 직접 입력하세요[1]. [2]\n\n"
        "추가 설명 (\n\n"
        "):\n"
        "오류 메시지는 텍스트로 입력할 수 있습니다[3]."
    )

    result = generate_answer(
        query="귀표 이미지 등록이 실패하면 어떻게 해야 하나요?",
        chunks=chunks,
        response_client=client,
        mode="normal",
    )

    assert "추가 설명" not in result.text
    assert ")\n:" not in result.text
    assert "[1][2]." in result.text
    assert len(result.cited_chunks) == 3
    assert "같은 내용을" in client.responses.calls[0]["input"]
    assert "최대 5문장" in client.responses.calls[0]["input"]


def test_direct_input_followup_keeps_ear_tag_context():
    messages = [
        {
            "role": "user",
            "content": "귀표 이미지 등록이 실패하면 어떻게 해야 하나요?",
        },
        {
            "role": "assistant",
            "content": "다른 사진으로 다시 시도하거나 귀표 번호를 직접 입력하세요.",
        },
    ]

    search_query = build_fallback_search_query(
        query="직접 입력은 어디서 하나요?",
        messages=messages,
    )
    route, chunks = retrieve_web_service_guide(search_query, max_chunks=2)

    assert "귀표 이미지 등록" in search_query
    assert "직접 입력은 어디서" in search_query
    assert route["route"] == "service_guide"
    assert "소 등록과 귀표 OCR" in chunks[0].section_path
    assert "`귀표 번호` 입력란" in chunks[0].content


def test_rewrite_keeps_web_service_context_when_model_drops_it(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    messages = [
        {
            "role": "user",
            "content": "귀표 이미지 등록이 실패하면 어떻게 해야 하나요?",
        },
        {
            "role": "assistant",
            "content": "귀표 번호를 직접 입력할 수 있습니다.",
        },
    ]
    client = FakeClient("번호를 직접 입력하는 위치는 어디인가요?")

    rewritten = rewrite_query(
        query="직접 입력은 어디서 하나요?",
        messages=messages,
        response_client=client,
    )

    assert rewritten == (
        "귀표 이미지 등록이 실패하면 어떻게 해야 하나요?와 관련하여 "
        "직접 입력은 어디서 하나요?"
    )

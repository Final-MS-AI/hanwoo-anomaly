from __future__ import annotations

from rag.rag_answer import (
    is_web_service_question,
    retrieve,
    retrieve_web_service_guide,
)


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

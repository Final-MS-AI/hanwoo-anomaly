from __future__ import annotations

from types import SimpleNamespace

from rag.rag_answer import RetrievedChunk, generate_answer


class FakeResponses:
    def __init__(self, output_text: str | list[str]):
        self.output_texts = (
            list(output_text)
            if isinstance(output_text, list)
            else [output_text]
        )
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        output_text = self.output_texts.pop(0)
        return SimpleNamespace(
            output_text=output_text,
            status="completed",
            incomplete_details=None,
        )


class FakeClient:
    def __init__(self, output_text: str | list[str]):
        self.responses = FakeResponses(output_text)


def chunk(
    content: str,
    reranker_score: float = 3.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        id="doc-1",
        document_title="테스트 방역 문서",
        document_type="guideline",
        page_start=1,
        page_end=1,
        section_path="구제역 > 이동 제한",
        content=content,
        score=1.0,
        reranker_score=reranker_score,
    )


def test_complete_ood_uses_general_knowledge_without_fake_citations(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    client = FakeClient("sorted() 함수나 list.sort() 메서드를 사용할 수 있습니다[1].")

    result = generate_answer(
        query="파이썬 리스트를 정렬하는 방법은?",
        chunks=[],
        response_client=client,
        mode="normal",
    )

    assert "일반적인 지식" in result.text
    assert "sorted()" in result.text
    assert "[1]" not in result.text
    assert result.cited_chunks == []


def test_out_of_document_livestock_question_has_health_warning(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    client = FakeClient("식욕이나 활동량이 달라질 수 있습니다.")

    result = generate_answer(
        query="소가 스트레스를 받을 때 나타나는 행동은?",
        chunks=[],
        response_client=client,
        mode="normal",
    )

    assert "일반적인 정보" in result.text
    assert "수의사" in result.text
    assert result.cited_chunks == []


def test_out_of_document_legal_question_is_conservative(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    client = FakeClient("일반적으로 신고 의무가 발생할 수 있습니다.")

    result = generate_answer(
        query="문서에 없는 축산 관련 법률상 신고 의무는 무엇인가요?",
        chunks=[],
        response_client=client,
        mode="normal",
    )

    assert "법적 근거" in result.text
    assert "최신 법령" in result.text
    assert result.cited_chunks == []


def test_model_document_scope_refusal_switches_to_general_fallback(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    client = FakeClient([
        "제공된 문서에서는 해당 내용을 확인할 수 없습니다.",
        "정확한 벌칙 금액은 최신 법령을 확인해야 합니다.",
    ])

    result = generate_answer(
        query="대한민국 우주개발 관련 법률의 벌칙 금액은 얼마인가요?",
        chunks=[chunk(
            "우주개발 관련 법률의 벌칙 금액은 별도 기준을 따른다",
            reranker_score=2.0,
        )],
        response_client=client,
        mode="normal",
    )

    assert "법적 근거" in result.text
    assert "최신 법령" in result.text
    assert "확인할 수 없습니다" not in result.text
    assert result.cited_chunks == []
    assert len(client.responses.calls) == 2


def test_strong_rag_refusal_retries_before_general_fallback(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    client = FakeClient([
        "제공된 문서에서는 해당 내용을 확인할 수 없습니다.",
        "구제역 의심축은 즉시 신고하고 이동을 제한해야 합니다[1].",
    ])

    result = generate_answer(
        query="구제역 의심축을 발견하면 무엇을 해야 하나요?",
        chunks=[chunk("구제역 의심축은 신고하고 이동을 제한해야 한다")],
        response_client=client,
        mode="normal",
    )

    assert "[1]" in result.text
    assert "일반적인 지식" not in result.text
    assert len(result.cited_chunks) == 1
    assert len(client.responses.calls) == 2


def test_out_of_document_biosecurity_question_prioritizes_authorities(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    client = FakeClient("일반적으로 출입을 줄이고 상황을 확인할 수 있습니다.")

    result = generate_answer(
        query="문서에 없는 가축전염병 방역 조치는 어떻게 하나요?",
        chunks=[],
        response_client=client,
        mode="normal",
    )

    assert "방역 지침" in result.text
    assert "관할 방역기관" in result.text
    assert "수의사" in result.text
    assert result.cited_chunks == []


def test_sufficient_rag_answer_keeps_citation_without_general_warning(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    client = FakeClient("구제역 의심축의 이동을 제한해야 합니다[1].")

    result = generate_answer(
        query="구제역 의심축의 이동 제한은 어떻게 하나요?",
        chunks=[chunk("구제역 의심축은 이동을 제한하고 관할 기관에 신고한다.")],
        response_client=client,
        mode="normal",
    )

    assert "[1]" in result.text
    assert "일반적인 지식" not in result.text
    assert len(result.cited_chunks) == 1


def test_mixed_answer_cites_only_document_section(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-model")
    client = FakeClient(
        "문서에서 확인된 내용:\n"
        "구제역 의심축은 이동을 제한해야 합니다[1].\n\n"
        "추가 설명:\n"
        "이 부분은 등록 문서의 직접 근거가 아닌 일반적인 지식입니다. "
        "스트레스 시 활동량이 달라질 수 있습니다."
    )

    result = generate_answer(
        query="구제역 의심축 이동 제한과 소의 일반적인 스트레스 행동도 알려주세요.",
        chunks=[chunk("구제역 의심축은 이동을 제한해야 한다.")],
        response_client=client,
        mode="normal",
    )

    assert "문서에서 확인된 내용" in result.text
    assert "추가 설명" in result.text
    assert "일반적인 지식" in result.text
    assert result.text.count("[1]") == 1
    assert len(result.cited_chunks) == 1

from __future__ import annotations

import os

import requests


API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000/rag/chat")


def post_chat(
    question: str,
    messages: list[dict[str, str]] | None = None,
    mode: str = "normal",
):
    return requests.post(
        API_URL,
        json={
            "question": question,
            "messages": messages or [],
            "mode": mode,
        },
        timeout=90,
    )


def test_fmd_initial_action():
    response = post_chat(
        "구제역 의심축을 발견하면 무엇을 해야 하나요?",
        mode="short",
    )

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]

    assert any(
        keyword in answer
        for keyword in (
            "신고",
            "방역기관",
            "1588-4060",
            "1588-9060",
        )
    )

    assert "즉시" in answer

    forbidden = [
        "살처분해야",
        "시료를 채취",
        "역학조사를 실시",
        "통제소를 설치",
    ]

    for keyword in forbidden:
        assert keyword not in answer


def test_legal_article_question():
    response = post_chat(
        "가축전염병 예방법 제11조에서 신고해야 하는 사람은 누구인가요?"
    )

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]
    sources = body["sources"]

    # 핵심 내용 확인
    assert "신고" in answer
    assert "소유자 또는 관리자" in answer
    assert "축산계열화사업자" in answer
    assert "수의사" in answer
    assert "연구책임자" in answer
    normalized_answer = (
        "".join(answer.split()).replace("·", "").replace("ㆍ", "")
    )
    assert all(
        keyword in normalized_answer
        for keyword in ("동물약품", "사료", "판매자")
    )

    # 인용/출처 확인
    assert "[1]" in answer
    assert len(sources) >= 1

    # 불필요한 제목/메타 문구가 다시 생기지 않는지 확인
    assert not answer.startswith("변:")
    assert "\n근거:" not in answer
    assert "\n참고(" not in answer
    assert "\n근거 및 요약 설명:" not in answer


def test_followup_conversation_context():
    messages = [
        {
            "role": "user",
            "content": "구제역 의심축을 발견하면 어디에 신고해야 하나요?",
        },
        {
            "role": "assistant",
            "content": (
                "구제역 신고 전용전화 1588-4060이나 "
                "1588-9060 또는 관할 방역기관에 즉시 신고해야 합니다."
            ),
        },
    ]

    response = post_chat(
        "그다음에는 무엇을 해야 하나요?",
        messages=messages,
        mode="normal",
    )

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]

    assert any(
        keyword in answer
        for keyword in (
            "농장을",
            "출입",
            "이동",
            "대기",
            "방역기관",
        )
    )

    # 이미 안내한 신고번호는 후속 답변에서 반복하지 않아야 함
    assert "1588-4060" not in answer
    assert "1588-9060" not in answer


def test_unrelated_question_uses_general_knowledge_without_sources():
    response = post_chat(
        "파이썬에서 리스트를 정렬하는 방법을 알려주세요."
    )

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]
    sources = body["sources"]

    assert answer
    assert "일반적인" in answer
    assert "문서" in answer
    assert "[1]" not in answer
    assert sources == []


def test_answer_citations_match_sources():
    response = post_chat(
        "축사시설현대화 지원사업의 지원 대상은 누구인가요?",
        mode="normal",
    )

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]
    sources = body["sources"]

    assert sources

    for index in range(1, len(sources) + 1):
        assert f"[{index}]" in answer

    # 실제 출처 수보다 큰 가짜 인용이 있으면 안 됨
    assert f"[{len(sources) + 1}]" not in answer

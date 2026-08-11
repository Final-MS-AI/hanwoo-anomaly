from __future__ import annotations

import os

import requests


API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000/rag/chat")

QUESTION = "축사시설현대화 지원사업의 지원 대상은 누구인가요?"


def normalize_meaning(text: str) -> str:
    return "".join(text.split()).replace("·", "").replace("ㆍ", "")


def assert_support_sections(answer: str, *, include_conditional: bool) -> None:
    normalized = normalize_meaning(answer)

    assert any(
        keyword in normalized
        for keyword in (
            "지원대상",
            "기본대상",
            "기본적으로지원",
            "지원받을수",
        )
    )
    assert any(
        keyword in normalized
        for keyword in (
            "추가인정",
            "추가로인정",
            "추가지원",
            "추가로지원",
        )
    )
    assert "제외" in normalized

    if include_conditional:
        assert any(
            keyword in normalized
            for keyword in (
                "조건부인정",
                "조건에따라인정",
                "조건을충족",
                "일정조건",
            )
        )


def call_rag(mode: str):
    return requests.post(
        API_URL,
        json={
            "question": QUESTION,
            "messages": [],
            "mode": mode,
        },
        timeout=90,
    )


def test_short_mode():
    response = call_rag("short")

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]
    sources = body["sources"]

    assert answer
    assert len(answer) <= 400

    assert "① 기본 대상" not in answer
    assert "② 추가 인정 대상" not in answer
    assert "③ 주요 지원 제외" not in answer
    assert "④ 조건부 인정" not in answer

    normalized = normalize_meaning(answer)
    assert any(
        keyword in normalized
        for keyword in (
            "농가",
            "농업법인",
            "축산업허가",
            "축산업등록",
            "스마트축산단지",
        )
    )

    assert "제외" in normalized

    assert 1 <= len(sources) <= 2


def test_normal_mode():
    response = call_rag("normal")

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]
    sources = body["sources"]

    assert_support_sections(answer, include_conditional=False)
    assert "④ 조건부 인정" not in answer

    assert 1 <= len(sources) <= 2


def test_detailed_mode():
    response = call_rag("detailed")

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]
    sources = body["sources"]

    assert_support_sections(answer, include_conditional=True)

    forbidden_meta = [
        "문서를 근거로 정리",
        "지침을 기준으로 정리",
        "위 내용은 제공된",
        "위 내용은 2026년",
        "참고:",
        "근거:",
    ]

    for text in forbidden_meta:
        assert text not in answer

    assert 1 <= len(sources) <= 2


def test_mode_length_order():
    short_response = call_rag("short")
    normal_response = call_rag("normal")
    detailed_response = call_rag("detailed")

    assert short_response.status_code == 200
    assert normal_response.status_code == 200
    assert detailed_response.status_code == 200

    short = short_response.json()["answer"]
    normal = normal_response.json()["answer"]
    detailed = detailed_response.json()["answer"]

    assert len(short) < len(normal)
    assert len(normal) < len(detailed)


def test_invalid_mode():
    response = call_rag("invalid")

    assert response.status_code == 422

    body = response.json()

    assert "detail" in body

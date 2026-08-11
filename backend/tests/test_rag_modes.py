from __future__ import annotations

import requests


API_URL = "http://127.0.0.1:8000/rag/chat"

QUESTION = "축사시설현대화 지원사업의 지원 대상은 누구인가요?"


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

    assert any(
        keyword in answer
        for keyword in (
            "지원 대상",
            "기본 대상",
            "대상이며",
        )
    )

    assert "제외" in answer

    assert 1 <= len(sources) <= 2


def test_normal_mode():
    response = call_rag("normal")

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]
    sources = body["sources"]

    assert "① 기본 대상" in answer
    assert "② 추가 인정 대상" in answer
    assert "③ 주요 지원 제외" in answer
    assert "④ 조건부 인정" not in answer

    assert 1 <= len(sources) <= 2


def test_detailed_mode():
    response = call_rag("detailed")

    assert response.status_code == 200

    body = response.json()
    answer = body["answer"]
    sources = body["sources"]

    assert "① 기본 대상" in answer
    assert "② 추가" in answer
    assert "③ 주요 지원 제외" in answer
    assert "④ 조건부 인정" in answer

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

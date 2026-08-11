from __future__ import annotations

import requests


API_URL = "http://127.0.0.1:8000/rag/chat"


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


def test_legal_article_question_stability():
    question = "가축전염병 예방법 제11조에서 신고해야 하는 사람은 누구인가요?"

    for attempt in range(5):
        response = post_chat(
            question,
            mode="normal",
        )

        assert response.status_code == 200, (
            f"{attempt + 1}번째 요청 실패: "
            f"status={response.status_code}"
        )

        body = response.json()
        answer = body["answer"]
        sources = body["sources"]

        # 핵심 신고 의무자
        assert "소유자 또는 관리자" in answer, (
            f"{attempt + 1}번째 응답에서 소유자/관리자 누락"
        )
        assert "축산계열화사업자" in answer, (
            f"{attempt + 1}번째 응답에서 축산계열화사업자 누락"
        )
        assert "수의사" in answer, (
            f"{attempt + 1}번째 응답에서 수의사 누락"
        )
        assert "연구책임자" in answer, (
            f"{attempt + 1}번째 응답에서 연구책임자 누락"
        )
        assert "동물약품 또는 사료 판매자" in answer, (
            f"{attempt + 1}번째 응답에서 판매자 누락"
        )

        # 인용 및 출처
        assert "[1]" in answer, (
            f"{attempt + 1}번째 응답에서 인용 누락"
        )
        assert len(sources) >= 1, (
            f"{attempt + 1}번째 응답에서 출처 누락"
        )

        # 이전에 발생했던 불필요한 출력 패턴
        assert not answer.startswith("변:"), (
            f"{attempt + 1}번째 응답이 '변:'으로 시작함:\n{answer}"
        )
        assert "\n근거:" not in answer, (
            f"{attempt + 1}번째 응답에 근거 메타 문구 발생:\n{answer}"
        )
        assert "\n참고(" not in answer, (
            f"{attempt + 1}번째 응답에 참고 제목 발생:\n{answer}"
        )
        assert "\n근거 및 요약 설명:" not in answer, (
            f"{attempt + 1}번째 응답에 요약 제목 발생:\n{answer}"
        )

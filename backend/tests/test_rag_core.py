from __future__ import annotations

from typing import Any

import pytest
import requests


API_URL = "http://127.0.0.1:8000/rag/chat"


TEST_CASES: list[dict[str, Any]] = [
    {
        "name": "구제역 신고 방법",
        "question": "구제역 의심축을 발견하면 어디에 신고해야 하나요?",
        "required_any": [
            "1588-4060",
            "1588-9060",
        ],
        "required_all": [
            "관할 방역기관",
            "즉시 신고",
        ],
        "forbidden": [
            "살처분",
            "시료채취",
            "역학조사",
            "통제소",
        ],
        "min_sources": 1,
        "max_sources": 2,
    },
    {
        "name": "구제역 신고 의무자",
        "question": (
            "가축전염병 예방법에서 죽거나 병든 가축을 "
            "신고해야 하는 의무자는 누구인가요?"
        ),
        "required_any": [
            "소유자",
            "관리자",
        ],
        "required_all": [
            "신고",
        ],
        "forbidden": [
            "1588-4060",
            "1588-9060",
            "지원 대상",
        ],
        "min_sources": 1,
        "max_sources": 4,
    },
    {
        "name": "축사시설현대화 지원 대상",
        "question": (
            "축사시설현대화 지원사업의 지원 대상과 "
            "신청 자격은 무엇인가요?"
        ),
        "required_any": [
            "축산업",
            "농업인",
            "농업법인",
            "허가",
            "등록",
        ],
        "required_all": [
            "기본 대상",
            "지원 제외",
        ],
        "forbidden": [
            "1588-4060",
            "구제역 신고",
            "시료채취",
        ],
        "min_sources": 1,
        "max_sources": 2,
    },
    {
        "name": "축사시설현대화 지원 제외",
        "question": (
            "축사시설현대화 지원사업에서 지원받을 수 없는 "
            "제외 대상은 무엇인가요?"
        ),
        "required_any": [
            "지원 제외",
            "제외",
            "미등록",
            "포기",
        ],
        "required_all": [],
        "forbidden": [
            "1588-4060",
            "구제역 신고",
            "시료채취",
            "역학조사",
        ],
        "min_sources": 1,
        "max_sources": 2,
    },
    {
        "name": "문서 범위 밖 질문",
        "question": "오늘 서울 날씨는 어떤가요?",
        "required_any": [
            "제공된 문서에서는 해당 내용을 확인할 수 없습니다",
            "확인할 수 없습니다",
        ],
        "required_all": [],
        "forbidden": [
            "1588-4060",
            "1588-9060",
            "구제역 신고",
            "이동을 중지",
        ],
        "min_sources": 0,
        "max_sources": 0,
    },
]


@pytest.fixture(scope="session", autouse=True)
def check_api_server() -> None:
    try:
        response = requests.get(
            "http://127.0.0.1:8000/docs",
            timeout=5,
        )
    except requests.RequestException as exc:
        pytest.fail(
            f"FastAPI 서버에 연결할 수 없습니다: {exc}"
        )

    assert response.status_code == 200, (
        f"FastAPI 서버 상태가 비정상입니다. "
        f"status={response.status_code}"
    )


@pytest.mark.parametrize(
    "test_case",
    TEST_CASES,
    ids=[case["name"] for case in TEST_CASES],
)
def test_core_rag_answers(
    test_case: dict[str, Any],
) -> None:
    response = requests.post(
        API_URL,
        json={
            "question": test_case["question"],
            "messages": [],
        },
        timeout=90,
    )

    assert response.status_code == 200, (
        f"API 요청 실패\n"
        f"status={response.status_code}\n"
        f"body={response.text}"
    )

    body = response.json()

    assert "answer" in body, (
        f"answer 필드가 없습니다: {body}"
    )

    assert "sources" in body, (
        f"sources 필드가 없습니다: {body}"
    )

    answer = str(body["answer"]).strip()
    sources = body["sources"]

    assert answer, "답변이 비어 있습니다."
    assert isinstance(sources, list), (
        f"sources가 리스트가 아닙니다: {sources}"
    )

    required_any = test_case["required_any"]

    if required_any:
        assert any(
            keyword in answer
            for keyword in required_any
        ), (
            f"필수 후보 문구가 하나도 없습니다.\n"
            f"후보={required_any}\n"
            f"질문={test_case['question']}\n"
            f"답변={answer}"
        )

    missing_all = [
        keyword
        for keyword in test_case["required_all"]
        if keyword not in answer
    ]

    assert not missing_all, (
        f"필수 문구 누락: {missing_all}\n"
        f"질문={test_case['question']}\n"
        f"답변={answer}"
    )

    forbidden_found = [
        keyword
        for keyword in test_case["forbidden"]
        if keyword in answer
    ]

    assert not forbidden_found, (
        f"금지 문구 포함: {forbidden_found}\n"
        f"질문={test_case['question']}\n"
        f"답변={answer}"
    )

    assert (
        test_case["min_sources"]
        <= len(sources)
        <= test_case["max_sources"]
    ), (
        f"출처 수가 예상 범위를 벗어났습니다.\n"
        f"expected="
        f"{test_case['min_sources']}~"
        f"{test_case['max_sources']}\n"
        f"actual={len(sources)}\n"
        f"sources={sources}"
    )

    for source in sources:
        assert source.get("id"), (
            f"출처 id가 없습니다: {source}"
        )
        assert source.get("title"), (
            f"출처 title이 없습니다: {source}"
        )
        assert source.get("page"), (
            f"출처 page가 없습니다: {source}"
        )

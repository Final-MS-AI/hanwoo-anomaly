from __future__ import annotations

from typing import Any

import pytest
import requests


API_URL = "http://127.0.0.1:8000/rag/chat"

COMMON_MESSAGES = [
    {
        "role": "user",
        "content": "구제역 의심축을 신고한 다음 농장주는 무엇을 해야 하나요?",
    },
    {
        "role": "assistant",
        "content": (
            "농장을 떠나지 말고 사람과 차량의 출입을 제한하면서 "
            "방역기관의 지시를 기다려야 합니다."
        ),
    },
]


TEST_CASES: list[dict[str, Any]] = [
    {
        "name": "일반 후속 행동",
        "question": "그다음에는 무엇을 해야 하나요?",
        "required": [
            "농장을 임의로 떠나지",
            "연락 가능한 상태",
            "사람과 차량의 출입을 제한",
            "방역기관의 지시에 따라",
        ],
        "forbidden": [
            "1588-4060",
            "1588-9060",
            "시료채취",
            "역학조사",
            "살처분",
        ],
        "max_sources": 3,
    },
    {
        "name": "농장 외출",
        "question": "그 농가는 밖으로 나가도 되나요?",
        "required": [
            "농장을 임의로 떠나지",
            "연락 가능한 상태",
        ],
        "forbidden": [
            "1588-4060",
            "시료채취",
            "역학조사",
        ],
        "max_sources": 3,
    },
    {
        "name": "차량 출입",
        "question": "차량은 들어와도 되나요?",
        "required": [
            "차량을 임의로 출입시키지",
            "세척·소독",
        ],
        "forbidden": [
            "통제소",
            "시료채취",
            "역학조사",
        ],
        "max_sources": 2,
    },
    {
        "name": "사료차 출입",
        "question": "사료차는 들어와도 되나요?",
        "required": [
            "차량을 임의로 출입시키지",
            "방역기관의 지시에 따라",
        ],
        "forbidden": [
            "1588-4060",
            "살처분",
        ],
        "max_sources": 2,
    },
    {
        "name": "가축 이동",
        "question": "가축을 다른 축사로 옮겨도 되나요?",
        "required": [
            "가축을 다른 축사로",
            "임의 이동시키지",
            "방역기관의 지시에 따라",
        ],
        "forbidden": [
            "지정도축장",
            "출하승인",
            "발생지역",
        ],
        "max_sources": 2,
    },
    {
        "name": "대기 기간",
        "question": "언제까지 농장에 있어야 하나요?",
        "required": [
            "정밀검사 결과",
            "연락 가능한 상태",
            "대기해야 합니다",
        ],
        "forbidden": [
            "임상수의사",
            "축산관련 종사자",
            "긴급한 경우",
        ],
        "max_sources": 1,
    },
    {
        "name": "직접 소독",
        "question": "제가 바로 소독해도 되나요?",
        "required": [
            "임의로 무리하게 소독하지",
            "방역기관의 지시",
            "안전을 확보",
        ],
        "forbidden": [
            "직접 소독해도 됩니다",
            "통제초소",
            "시료채취",
        ],
        "max_sources": 2,
    },
    {
        "name": "가족 직원 출입",
        "question": "가족이나 직원은 농장에 들어와도 되나요?",
        "required": [
            "가족이나 직원도",
            "임의로 출입시키지",
            "소독",
        ],
        "forbidden": [
            "1588-4060",
            "역학조사",
            "시료채취",
        ],
        "max_sources": 2,
    },
    {
        "name": "분뇨 장비 반출",
        "question": "분뇨나 장비를 밖으로 내보내도 되나요?",
        "required": [
            "분뇨·장비·물품",
            "임의 반출하지",
            "세척·소독",
        ],
        "forbidden": [
            "제공된 문서에서는 해당 내용을 확인할 수 없습니다",
            "공동처리시설",
            "지정처리시설",
        ],
        "max_sources": 2,
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
        f"FastAPI 서버 상태가 비정상입니다: "
        f"status={response.status_code}"
    )


@pytest.mark.parametrize(
    "test_case",
    TEST_CASES,
    ids=[case["name"] for case in TEST_CASES],
)
def test_fmd_followup_action(
    test_case: dict[str, Any],
) -> None:
    payload = {
        "question": test_case["question"],
        "messages": COMMON_MESSAGES,
    }

    response = requests.post(
        API_URL,
        json=payload,
        timeout=60,
    )

    assert response.status_code == 200, (
        f"API 요청 실패: "
        f"status={response.status_code}, "
        f"body={response.text}"
    )

    body = response.json()

    assert "answer" in body, (
        f"응답에 answer 필드가 없습니다: {body}"
    )

    assert "sources" in body, (
        f"응답에 sources 필드가 없습니다: {body}"
    )

    answer = str(body["answer"])
    sources = body["sources"]

    assert answer.strip(), "답변이 비어 있습니다."

    missing = [
        keyword
        for keyword in test_case["required"]
        if keyword not in answer
    ]

    forbidden_found = [
        keyword
        for keyword in test_case["forbidden"]
        if keyword in answer
    ]

    assert not missing, (
        f"필수 문구 누락: {missing}\n"
        f"질문: {test_case['question']}\n"
        f"답변: {answer}"
    )

    assert not forbidden_found, (
        f"금지 문구 포함: {forbidden_found}\n"
        f"질문: {test_case['question']}\n"
        f"답변: {answer}"
    )

    assert isinstance(sources, list), (
        f"sources가 리스트가 아닙니다: {sources}"
    )

    assert 1 <= len(sources) <= test_case["max_sources"], (
        f"출처 수가 예상 범위를 벗어났습니다. "
        f"expected=1~{test_case['max_sources']}, "
        f"actual={len(sources)}, "
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
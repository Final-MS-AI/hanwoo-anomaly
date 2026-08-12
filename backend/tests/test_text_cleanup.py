from rag.rag_answer import clean_generated_text, clean_service_guide_text


def test_remove_answer_prefix():
    text = "변:\n제11조에 따라 신고해야 합니다."

    result = clean_generated_text(text)

    assert result == "제11조에 따라 신고해야 합니다."


def test_remove_normal_answer_prefix():
    text = "답변:\n제11조에 따라 신고해야 합니다."

    result = clean_generated_text(text)

    assert result == "제11조에 따라 신고해야 합니다."


def test_remove_summary_heading():
    text = (
        "제11조에 따라 신고해야 합니다.\n\n"
        "근거 및 요약 설명:\n"
        "- 제11조 제1항입니다."
    )

    result = clean_generated_text(text)

    assert "근거 및 요약 설명:" not in result
    assert "제11조 제1항입니다." in result


def test_remove_reference_heading():
    text = (
        "제11조에 따라 신고해야 합니다.\n\n"
        "참고(관련 조항):\n"
        "- 제11조 제2항입니다."
    )

    result = clean_generated_text(text)

    assert "참고(관련 조항):" not in result
    assert "제11조 제2항입니다." in result


def test_fix_escaped_tilde():
    text = "제1항\\~제3항을 확인합니다."

    result = clean_generated_text(text)

    assert result == "제1항~제3항을 확인합니다."


def test_remove_trailing_meta_reference():
    text = (
        "제11조에 따라 신고해야 합니다[1].\n\n"
        "근거: 가축전염병 예방법 제11조 본문 및 관련 항[1]."
    )

    result = clean_generated_text(text)

    assert "근거:" not in result
    assert "제11조에 따라 신고해야 합니다[1]." in result


def test_preserve_valid_citation():
    text = "소유자 또는 관리자는 신고해야 합니다[1]."

    result = clean_generated_text(text)

    assert "[1]" in result
    assert result == "소유자 또는 관리자는 신고해야 합니다[1]."

def test_remove_core_evidence_exception_heading():
    text = (
        "핵심 근거 및 예외사항:\n"
        "- 제11조 제1항입니다."
    )

    result = clean_generated_text(text)

    assert "핵심 근거" not in result
    assert "예외사항:" not in result
    assert "사항:" not in result
    assert result == "- 제11조 제1항입니다."

def test_remove_standalone_evidence_heading():
    text = (
        "수의사는 신고 의무자입니다[1].\n\n"
        "근거:\n"
        "가축전염병 예방법 제11조에 근거합니다[1]."
    )

    cleaned = clean_generated_text(text)

    assert "\n근거:" not in cleaned
    assert "가축전염병 예방법 제11조에 근거합니다[1]." in cleaned

def test_remove_followup_offer():
    text = (
        "분석 결과입니다[1].\n\n"
        "만약 특정 발생사례에 대해 구체적 분석을 원하시면, "
        "관련 자료를 알려주시면 추가 분석 방법을 안내해 드리겠습니다."
    )

    cleaned = clean_generated_text(text)

    assert cleaned == "분석 결과입니다[1]."

def test_fix_broken_date_after_empty_list_marker():
    text = (
        "지원 대상\n\n"
        "-\n"
        "  2014.\n"
        "        12. 31 이전에 축산업 허가를 받은 농업인[1]."
    )

    cleaned = clean_generated_text(text)

    assert cleaned == (
        "지원 대상\n\n"
        "2014. 12. 31 이전에 축산업 허가를 받은 농업인[1]."
    )

def test_remove_standalone_direct_answer_heading():
    text = (
        "분야: 지원사업\n\n"
        "직접적 답변:\n"
        "- 지원조건은 융자 80%·자부담 20%입니다[1]."
    )

    cleaned = clean_generated_text(text)

    assert "직접적 답변" not in cleaned
    assert "지원조건은 융자 80%·자부담 20%입니다[1]." in cleaned


def test_remove_broken_additional_explanation_heading():
    text = (
        "다른 사진으로 다시 시도하세요[1].\n\n"
        "추가 설명 (\n\n"
        "):\n"
        "귀표 번호를 직접 입력할 수도 있습니다[2]."
    )

    cleaned = clean_service_guide_text(clean_generated_text(text))

    assert "추가 설명" not in cleaned
    assert "\n):" not in cleaned
    assert "귀표 번호를 직접 입력" in cleaned


def test_merge_standalone_citation_at_paragraph_end():
    text = "다른 사진으로 다시 시도하세요[1]. [2]"

    cleaned = clean_generated_text(text)

    assert cleaned == "다른 사진으로 다시 시도하세요[1][2]."

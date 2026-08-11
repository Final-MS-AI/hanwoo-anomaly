
from pathlib import Path
import json, re

CONFIG_PATH = (
    Path(__file__).resolve().parent
    / "router_config.json"
)

if not CONFIG_PATH.exists():
    raise FileNotFoundError(
        f"라우터 설정 파일을 찾을 수 없습니다: {CONFIG_PATH}"
    )

CONFIG = json.loads(
    CONFIG_PATH.read_text(encoding="utf-8")
)

def anyof(q, terms):
    return any(t in q for t in terms)

def standalone_law(q):
    return re.search(r"(?<![가-힣A-Za-z0-9])법(?![가-힣A-Za-z0-9])", q) is not None

def route_query(query):
    q = re.sub(r"\s+", " ", query.lower()).strip()

    fmd_context = anyof(
        q,
        (
            "구제역",
            "의심축",
            "가축전염병",
        ),
    )

    legal_context = anyof(
        q,
        (
            "가축전염병",
            "예방법",
            "법적",
            "법률",
            "조문",
            "신고",
            "제11조",
            "의무",
        ),
    )

    outbreak_context = anyof(
        q,
        (
            "구제역",
            "가축전염병",
            "역학",
            "발생 농장",
            "발생농장",
        ),
    )

    support = (
        "축사시설현대화", "fta기금", "농특회계", "이차보전",
        "지원사업", "지원대상", "사업대상", "지원조건",
        "사업 신청", "대상자 선정", "융자", "자부담",
        "지원 가능한", "지원 가능", "대출 가능",
        "대출 실행", "시설과 설비",
    )

    legal = (
        "법률", "시행령", "시행규칙", "조문", "몇 조",
        "신고 의무", "법적 의무", "과태료", "벌칙",
        "처벌", "허가", "등록", "대통령령", "기본계획",
        "실태조사", "몇 년마다", "몇 종 가축전염병",
        "농장식별번호", "농업재해의 정의", "가축분뇨",
        "축사시설에는",
    )

    legal_subject = (
        "의무자는 누구",
        "의무자",
        "누가 신고",
        "누구가 신고",
        "누가 해야",
        "신고 주체",
        "책임자는 누구",

        # 신고 대상자 표현
        "신고해야 하는 사람",
        "신고 대상자",
        "신고 대상",
        "신고 의무가 있는 사람",
        "신고 의무가 있나요",

        # 법령상 주체
        "소유자나 관리자",
        "소유자 또는 관리자",
        "연구책임자",
        "축산계열화사업자",
        "가축운송업자",
        "동물약품",
        "사료 판매자",

        # 법령 조문 직접 질문
        "예방법 제",
        "예방법상",
    )

    field = (
        "의심축", "초동방역", "이동중지", "이동 제한",
        "이동제한", "살처분", "매몰", "청소", "세척",
        "소독", "시료 채취", "시료채취", "시료 송부",
        "거점소독시설", "위기경보", "임상관찰", "예찰",
        "긴급 백신접종", "현장 조치", "대응요령",
        "행동요령", "역학조사는 어떤 순서",
        "어떤 순서로 진행", "어떻게 시행",
        "현장에서 어떤 조치", "절차는",
    )

    field_contextual = (
        "신고 후",
        "신고 이후",
        "신고를 한 뒤",
        "의심 신고",

        "농장 밖으로",
        "들어오게 해도",
        "들어와도",
        "출입",
        "외부 차량",
        "사료차",
        "다른 축사로",
        "옮겨도",
        "가축 이동",

        "언제까지 기다려",
        "기다려야",
        "대기",

        "가족이나 직원",
        "가족",
        "직원",

        "분뇨",
        "장비 반출",
        "반출",

        "통제",
        "관리해야",
        "사람, 차량",
        "사람, 차량, 가축",

        "현장 대응 절차",
        "전체적으로 정리",
    )

    outbreak = (
        "2023년",
        "발생 원인",
        "유입 원인",
        "전파 원인",
        "유전형",
        "상동성",
        "발생농장 간",
        "역학조사 결과",
        "불법 반입",
        "농장 간 전파",
        "역학조사위원회",
        "권고사항",

        # 역학조사 일반
        "역학조사",
        "역학관계",
        "역학 관계",

        # 발생 상황 분석
        "발생 상황",
        "발생 농장",
        "발생 전후",
        "발생 시",

        # 전파·이동 분석
        "전파 경로",
        "이동 내역",
        "사람과 차량",
        "인접 농장",
        "가축 이동 내역",

        # 위험 분석
        "위험요인",
        "위험 요인",
        "분석할 때",
        "분석하는 기준",
    )

    disease = (
        "구제역이란",
        "증상",
        "잠복기",

        # 감염·전파
        "감염경로",
        "전파방법",
        "어떻게 전파",
        "전파되나요",
        "감염되기 쉬운",
        "감염축",

        # 임상 상태
        "발굽",
        "입이나 발굽",
        "의심되는 소",
        "일반적인 상태",

        # 백신·검사
        "백신",
        "항체",
        "항체양성률",
        "검사", "진단", "바이러스", "병원체", "키트",
        "민감도", "특이도", "real-time rt-pcr",
        "rt-pcr", "시료는 무엇", "carrier", "캐리어",
        "제어하기 어려운", "오해하기 쉬운 질병",
        "감별진단", "전파될 가능성",
        "질병이라고 하는 이유",
    )

    if (
        anyof(q, support)
        and (
            anyof(
                q,
                (
                    "법적", "법률", "시행령",
                    "허가", "등록", "법적 기준",
                    "축사시설 기준",
                ),
            )
            or standalone_law(q)
        )
    ):
        route = "composite_support_legal"

    # 법적 의무자·책임 주체 질문은 법령 검색을 우선한다.
    elif (
        legal_context
        and anyof(q, legal_subject)
    ):
        route = "legal"

    elif (
        anyof(q, ("백신", "항체", "항체양성률"))
        and anyof(
            q,
            ("기준 미달", "미달", "현장 대응",
             "현장 조치", "조치", "대응"),
        )
    ):
        route = "composite_vaccine"

    elif (
        outbreak_context
        and anyof(q, outbreak)
        and anyof(
            q,
            ("조치", "대응", "재발 방지", "방역", "행동"),
        )
    ):
        route = "composite_outbreak_action"

    elif (
        (
            anyof(q, ("법적", "법률", "신고 의무", "법적 신고"))
            or standalone_law(q)
        )
        and anyof(
            q,
            ("현장", "조치", "행동", "발견", "대응"),
        )
    ):
        route = "composite_legal_action"

    elif (
        fmd_context
        and anyof(
            q,
            (
                "어떻게 해야",
                "해도 되나요",
                "반출",
                "출입",
                "옮겨도",
                "통제",
                "관리해야",
                "기다려야",
            ),
        )
        and anyof(
            q,
            (
                "가축",
                "장비",
                "차량",
                "사람",
                "농장",
                "분뇨",
            ),
        )
    ):
        route = "field_action"

    elif anyof(q, support):
        route = "support_program"

    elif anyof(q, legal) or standalone_law(q):
        route = "legal"

    elif (
        outbreak_context
        and anyof(q, outbreak)
    ):
        route = "outbreak_analysis"

    elif (
        anyof(q, field)
        or (
            fmd_context
            and anyof(q, field_contextual)
        )
    ):
        route = "field_action"

    elif anyof(q, disease):
        route = "disease_info"

    else:
        route = CONFIG["default_route"]

    rule = CONFIG["routes"][route]

    return {
        "route": route,
        "filter": rule.get("filter"),
        "top_k": rule.get("top_k", 10),
    }
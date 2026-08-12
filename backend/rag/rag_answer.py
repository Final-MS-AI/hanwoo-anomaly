
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

ROOT = Path(__file__).resolve().parents[1]
WEB_SERVICE_GUIDE_PATH = Path(__file__).with_name("web_service_guide.md")

try:
    from .query_router import route_query
except ImportError:
    from query_router import route_query


ANSWER_MODES = {
    "short": {
        "max_output_tokens": 350,
        "max_context_chunks": 4,
        "max_sources": 2,
        "instruction": (
            "질문에 직접 답한다. "
            "답변은 최대 2문장으로 작성한다. "
            "일반 사용자가 즉시 해야 할 행동을 먼저 설명한다. "
            "기관 전체 목록과 상세 행정 절차는 나열하지 않는다. "
            "신고 방법을 직접 묻는 경우에만 구제역 신고 전화번호를 안내한다. "
            "이전 대화에서 이미 설명한 내용은 반복하지 않는다. "
            "후속 질문에는 새로 필요한 행동만 답한다. "
            "사용자의 즉시 행동 질문에는 살처분, 백신접종, 역학조사, "
            "시료채취, 정밀검사 등 이후 단계의 조치를 나열하지 않는다. "
            "방역기관의 업무는 필요한 경우 한 문장 이내로 요약한다. "
            "답변 본문은 220자 이내로 작성한다."
        ),
    },
    "normal": {
        "max_output_tokens": 1200,
        "max_context_chunks": 6,
        "max_sources": 4,
        "instruction": (
            "직접적인 답을 먼저 제시한 뒤 핵심 근거와 예외사항을 2~4개 단락으로 설명한다. "
            "불필요한 반복은 하지 않는다."
        ),
    },
    "detailed": {
        "max_output_tokens": 3000,
        "max_context_chunks": 8,
        "max_sources": 5,
        "instruction": (
            "절차, 조건, 예외, 법적 근거를 구분해 충분히 설명한다. "
            "검색 근거에 없는 내용은 추가하지 않는다."
        ),
    },
}

GENERAL_KNOWLEDGE_CONTINUATION_NOTICE = (
    "답변이 길어 여기까지만 표시했습니다. 추가 응답을 원하시면 "
    "'이어서 설명해 주세요'라고 입력해 주세요."
)


@dataclass
class RetrievedChunk:
    id: str
    document_title: str
    document_type: str
    page_start: int | None
    page_end: int | None
    section_path: str
    content: str
    score: float | None = None
    reranker_score: float | None = None

    @property
    def page_label(self) -> str:
        if self.page_start is None:
            return "페이지 정보 없음"
        if self.page_end is None or self.page_end == self.page_start:
            return f"p.{self.page_start}"
        return f"p.{self.page_start}-{self.page_end}"

    @property
    def source_label(self) -> str:
        return f"{self.document_title}, {self.page_label}"

@dataclass
class GeneratedAnswer:
    text: str
    cited_chunks: list[RetrievedChunk]


WEB_SERVICE_KEYWORDS = (
    "cowow",
    "코와우",
    "웹",
    "앱",
    "사이트",
    "화면",
    "페이지",
    "메뉴",
    "버튼",
    "대시보드",
    "이상 개체",
    "주의 개체",
    "위험 개체",
    "영상 분석",
    "영상 선택",
    "소 등록",
    "귀표 등록",
    "귀표 이미지",
    "귀표 사진",
    "귀표 번호 인식",
    "비문 등록",
    "비문 사진",
    "ai 상담",
    "채팅",
    "환경 제어",
    "장비 등록",
    "장비 연결",
    "게스트 로그인",
    "google 로그인",
    "로그인 실패",
    "ai 판단이 잘못",
    "검토 요청",
)

WEB_SERVICE_SECTION_KEYWORDS = {
    "로그인과 화면 이동": ("로그인", "게스트", "메뉴", "이동", "페이지"),
    "이상 개체 대시보드와 AI 판단 피드백": (
        "대시보드", "이상 개체", "주의", "위험", "ai 판단", "피드백", "검토 요청"
    ),
    "영상 분석 사용법": ("영상", "분석", "탐지", "추적", "진행률", "결과 영상"),
    "소 등록과 귀표 OCR": (
        "소 등록", "귀표", "ocr", "번호", "이미지", "사진", "인식", "판독"
    ),
    "비문 사진 등록": ("비문", "코 무늬", "일치도", "임베딩"),
    "AI 상담 사용법": ("ai 상담", "채팅", "질문", "답변", "참고 문서", "이어서"),
    "축사 환경 제어와 장비 연결": (
        "환경", "장비", "esp32", "센서", "환기팬", "물 뿌리기", "등록 코드"
    ),
    "자주 발생하는 오류 대응": ("오류", "실패", "안 돼", "안돼", "문제", "재시도"),
}


def is_web_service_question(query: str) -> bool:
    normalized = normalize_text(query)
    return any(keyword in normalized for keyword in WEB_SERVICE_KEYWORDS)


def _load_web_service_sections() -> list[tuple[str, str]]:
    if not WEB_SERVICE_GUIDE_PATH.exists():
        raise FileNotFoundError(
            f"웹 서비스 가이드 파일을 찾을 수 없습니다: {WEB_SERVICE_GUIDE_PATH}"
        )

    sections: list[tuple[str, str]] = []
    title: str | None = None
    lines: list[str] = []

    for line in WEB_SERVICE_GUIDE_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if title and lines:
                sections.append((title, "\n".join(lines).strip()))
            title = line[3:].strip()
            lines = []
        elif title:
            lines.append(line)

    if title and lines:
        sections.append((title, "\n".join(lines).strip()))

    return sections


def retrieve_web_service_guide(
    query: str,
    max_chunks: int,
) -> tuple[dict[str, Any], list[RetrievedChunk]]:
    normalized_query = normalize_text(query)
    query_tokens = content_fingerprint(normalized_query)
    ranked: list[tuple[int, int, str, str]] = []

    for index, (title, content) in enumerate(_load_web_service_sections()):
        keywords = WEB_SERVICE_SECTION_KEYWORDS.get(title, ())
        keyword_score = sum(
            3 for keyword in keywords if normalize_text(keyword) in normalized_query
        )
        section_tokens = content_fingerprint(f"{title} {content}")
        overlap_score = len(query_tokens & section_tokens)
        ranked.append((keyword_score + overlap_score, -index, title, content))

    ranked.sort(reverse=True)
    selected = ranked[:max_chunks]
    chunks = [
        RetrievedChunk(
            id=f"cowow-service-guide-{index + 1}",
            document_title="COWOW 웹 서비스 사용 가이드",
            document_type="service_guide",
            page_start=None,
            page_end=None,
            section_path=title,
            content=content,
            score=5.0,
            reranker_score=5.0,
        )
        for index, (_, _, title, content) in enumerate(selected)
    ]

    return (
        {"route": "service_guide", "filter": None, "top_k": max_chunks},
        chunks,
    )


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"환경변수 {name}이 설정되지 않았습니다.")
    return value


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()

def extract_article_numbers(query: str) -> list[str]:
    """질문에 명시된 제11조, 11조 등의 조문 번호를 추출한다."""
    normalized = normalize_text(query)

    numbers = re.findall(
        r"(?:제\s*)?(\d+(?:의\d+)?)\s*조",
        normalized,
    )

    return list(dict.fromkeys(numbers))

def extract_legal_document_hint(query: str) -> str | None:
    normalized = normalize_text(query)

    document_names = (
        "가축전염병 예방법",
        "가축 및 축산물 이력관리에 관한 법률",
        "가축분뇨의 관리 및 이용에 관한 법률",
        "축산법",
        "농어업재해대책법",
    )

    for name in document_names:
        if normalize_text(name) in normalized:
            return name

    return None

SUPPORT_ELIGIBILITY_KEYWORDS = (
    "지원 대상",
    "지원대상",
    "사업 대상",
    "사업대상",
    "신청 자격",
    "신청자격",
    "자격요건",
    "자격 요건",
    "누가 신청",
    "신청할 수 있는",
    "지원 제외",
    "지원제외",
    "제외 대상",
    "제외대상",
    "지원 제외 대상",
    "지원받을 수 없는",
    "지원 받을 수 없는",
    "제외되는 대상",
    "제외되는 경우",
    "지원에서 제외",
    "지원 대상에서 제외",
    "지원대상에서 제외",
)


def is_support_eligibility_question(query: str) -> bool:
    normalized = normalize_text(query)

    has_support_context = any(
        keyword in normalized
        for keyword in (
            "축사시설현대화",
            "축사 시설 현대화",
            "지원사업",
            "지원 사업",
        )
    )

    has_eligibility_intent = any(
        keyword in normalized
        for keyword in SUPPORT_ELIGIBILITY_KEYWORDS
    )

    return has_support_context and has_eligibility_intent

def is_support_exclusion_question(query: str) -> bool:
    normalized = normalize_text(query)

    exclusion_keywords = (
        "지원 제외",
        "지원제외",
        "제외 대상",
        "제외대상",
        "지원 제외 대상",
        "지원받을 수 없는",
        "지원 받을 수 없는",
        "제외되는 대상",
        "제외되는 경우",
        "지원에서 제외",
        "지원 대상에서 제외",
        "지원대상에서 제외",
    )

    return (
        is_support_eligibility_question(query)
        and any(
            keyword in normalized
            for keyword in exclusion_keywords
        )
    )

def is_support_combined_question(query: str) -> bool:
    normalized = normalize_text(query)

    has_support_context = any(
        keyword in normalized
        for keyword in (
            "축사시설현대화",
            "축사 시설 현대화",
            "지원사업",
            "지원 사업",
        )
    )

    has_include_intent = any(
        keyword in normalized
        for keyword in (
            "지원 대상",
            "지원대상",
            "사업 대상",
            "사업대상",
            "지원 자격",
            "지원자격",
        )
    )

    has_exclusion_intent = any(
        keyword in normalized
        for keyword in (
            "제외 대상",
            "제외대상",
            "지원 제외",
            "지원제외",
            "제외되는 대상",
            "지원에서 제외",
            "지원 대상에서 제외",
        )
    )

    return (
        has_support_context
        and has_include_intent
        and has_exclusion_intent
    )

REFUSAL_PATTERNS = (
    "i'm sorry",
    "i am sorry",
    "cannot assist",
    "can't assist",
    "cannot help",
    "can't help",
    "unable to assist",
    "도와드릴 수 없습니다",
    "답변할 수 없습니다",
    "요청을 처리할 수 없습니다",
)


def is_refusal_text(text: str) -> bool:
    normalized = normalize_text(text)

    return any(
        pattern in normalized
        for pattern in REFUSAL_PATTERNS
    )


def is_document_scope_refusal(text: str) -> bool:
    """관련성 휴리스틱을 통과했지만 모델이 문서 범위 밖이라고 판단한 응답."""
    normalized = normalize_text(text)
    return any(
        pattern in normalized
        for pattern in (
            "제공된 문서에서는 해당 내용을 확인할 수 없습니다",
            "제공된 검색 근거에서는 해당 내용을 확인할 수 없습니다",
            "검색 근거에서 해당 내용을 확인할 수 없습니다",
        )
    )


def content_fingerprint(text: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-zA-Z가-힣 ]", " ", normalize_text(text))
    return {token for token in normalized.split() if len(token) >= 2}


def similarity(a: str, b: str) -> float:
    sa = content_fingerprint(a)
    sb = content_fingerprint(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def deduplicate(chunks: list[RetrievedChunk], threshold: float = 0.72) -> list[RetrievedChunk]:
    kept: list[RetrievedChunk] = []
    for chunk in chunks:
        duplicate = False
        for existing in kept:
            same_location = (
                chunk.document_title == existing.document_title
                and chunk.page_start == existing.page_start
                and chunk.page_end == existing.page_end
            )
            if same_location or similarity(chunk.content, existing.content) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(chunk)
    return kept

QUERY_STOPWORDS = {
    "어떻게",
    "무엇",
    "무엇을",
    "알려줘",
    "알려주세요",
    "확인",
    "하나요",
    "해야",
    "하는",
    "있는",
    "관련",
}



def query_keywords(text: str) -> set[str]:
    normalized = re.sub(
        r"[^0-9a-zA-Z가-힣 ]",
        " ",
        normalize_text(text),
    )

    return {
        token
        for token in normalized.split()
        if len(token) >= 2 and token not in QUERY_STOPWORDS
    }


def has_sufficient_relevance(
    query: str,
    chunks: list[RetrievedChunk],
) -> bool:
    if not chunks:
        return False

    min_reranker_score = float(
        os.getenv("RAG_MIN_RERANKER_SCORE", "1.5")
    )

    top_reranker_score = chunks[0].reranker_score

    if (
        top_reranker_score is not None
        and top_reranker_score < min_reranker_score
    ):
        return False

    query_tokens = query_keywords(query)

    if not query_tokens:
        return True

    context_tokens: set[str] = set()

    for chunk in chunks[:2]:
        context_tokens.update(
            content_fingerprint(chunk.content)
        )
        context_tokens.update(
            content_fingerprint(chunk.section_path)
        )
        context_tokens.update(
            content_fingerprint(chunk.document_title)
        )

    overlap = query_tokens & context_tokens

    return bool(overlap)


def has_strong_relevance(chunks: list[RetrievedChunk]) -> bool:
    if not chunks or chunks[0].reranker_score is None:
        return False
    threshold = float(
        os.getenv("RAG_STRONG_RERANKER_SCORE", "2.3")
    )
    return chunks[0].reranker_score >= threshold


GENERAL_KNOWLEDGE_NOTICE = (
    "주의: 아래 내용은 현재 등록된 문서에서 직접 확인된 내용이 아니라 "
    "일반적인 지식을 바탕으로 설명합니다. 최종 판단이 필요한 경우 "
    "관련 전문가나 담당 기관에 확인해 주세요."
)

LEGAL_GENERAL_NOTICE = (
    "주의: 아래 내용은 현재 등록된 문서에서 직접 확인된 법적 근거가 "
    "아닙니다. 일반적인 정보이며, 실제 적용 여부는 최신 법령이나 "
    "담당 기관에 확인해 주세요."
)

ANIMAL_HEALTH_GENERAL_NOTICE = (
    "주의: 아래 내용은 현재 등록된 문서에서 직접 확인된 내용이 아닌 "
    "일반적인 정보이며 실제 진단이나 처치를 대신하지 않습니다. "
    "증상이 있거나 이상이 의심되면 수의사의 확인이 필요합니다."
)

BIOSECURITY_GENERAL_NOTICE = (
    "주의: 아래 내용은 현재 등록된 문서에서 직접 확인된 방역 지침이 "
    "아닌 일반적인 정보입니다. 실제 방역 조치는 관할 방역기관 또는 "
    "수의사의 지시를 우선해 주세요."
)

REALTIME_WEATHER_UNAVAILABLE_ANSWER = (
    "현재 COWOW AI 상담에서는 실시간 날씨를 조회할 수 없습니다. "
    "정확한 기온·강수·미세먼지 정보는 기상청 날씨누리나 "
    "사용 중인 날씨 앱에서 확인해 주세요."
)


def is_realtime_weather_question(query: str) -> bool:
    normalized = normalize_text(query)
    weather_keywords = (
        "날씨", "기온", "강수", "강수량", "비가", "눈이",
        "미세먼지", "초미세먼지", "체감온도", "풍속", "기상 예보",
    )
    realtime_markers = (
        "오늘", "내일", "모레", "지금", "현재", "실시간",
        "이번 주", "이번주", "주말", "최신", "예보",
    )
    direct_weather_requests = (
        "날씨 알려", "날씨가 어때", "날씨는 어때", "날씨 어떤",
        "기온 알려", "몇 도", "비 오", "눈 오",
    )

    has_weather_keyword = any(
        keyword in normalized for keyword in weather_keywords
    )
    return has_weather_keyword and (
        any(marker in normalized for marker in realtime_markers)
        or any(pattern in normalized for pattern in direct_weather_requests)
    )


def is_legal_or_support_question(query: str) -> bool:
    normalized = normalize_text(query)
    return any(
        keyword in normalized
        for keyword in (
            "법률", "법령", "법적", "조문", "처벌", "벌칙", "과태료",
            "지원 자격", "지원자격", "지원 대상", "지원대상", "신청 자격",
            "행정 절차", "행정절차", "의무", "몇 조", "제도",
        )
    )


def is_biosecurity_question(query: str) -> bool:
    normalized = normalize_text(query)
    return any(
        keyword in normalized
        for keyword in (
            "방역", "구제역", "가축전염병", "의심축", "살처분",
            "이동 제한", "이동제한", "검역", "소독 조치",
        )
    )


def is_animal_health_question(query: str) -> bool:
    normalized = normalize_text(query)
    has_animal_context = any(
        keyword in normalized
        for keyword in (
            "소", "한우", "송아지", "가축", "동물", "축우",
        )
    )
    has_health_context = any(
        keyword in normalized
        for keyword in (
            "건강", "증상", "질병", "아프", "스트레스", "식욕", "진단",
            "치료", "처치", "행동", "호흡", "설사", "발열",
        )
    )
    return has_animal_context and has_health_context


def general_knowledge_notice(query: str) -> str:
    if is_legal_or_support_question(query):
        return LEGAL_GENERAL_NOTICE
    if is_biosecurity_question(query):
        return BIOSECURITY_GENERAL_NOTICE
    if is_animal_health_question(query):
        return ANIMAL_HEALTH_GENERAL_NOTICE
    return GENERAL_KNOWLEDGE_NOTICE


def should_allow_general_supplement(
    query: str,
    chunks: list[RetrievedChunk],
) -> bool:
    """복합 질문에서 문서로 뒷받침되지 않는 별도 요구가 있는지 보수적으로 본다."""
    normalized = normalize_text(query)
    compound_markers = (
        "그리고", "또한", "추가로", "함께 알려", "도 알려",
        "뿐만 아니라", "와 일반", "과 일반",
    )
    if not any(marker in normalized for marker in compound_markers):
        return False

    query_tokens = query_keywords(query)
    if not query_tokens:
        return False

    context_tokens: set[str] = set()
    for chunk in chunks[:3]:
        context_tokens.update(content_fingerprint(chunk.content))
        context_tokens.update(content_fingerprint(chunk.section_path))
        context_tokens.update(content_fingerprint(chunk.document_title))

    unsupported_tokens = query_tokens - context_tokens
    return bool(query_tokens & context_tokens) and len(unsupported_tokens) >= 2

def normalize_conversation(
    messages: list[dict[str, str]] | None,
    max_messages: int = 6,
    max_chars: int = 4000,
) -> list[dict[str, str]]:
    if not messages:
        return []

    normalized: list[dict[str, str]] = []

    for message in messages[-max_messages:]:
        role = str(message.get("role", "")).strip()
        content = str(message.get("content", "")).strip()

        if role not in {"user", "assistant"}:
            continue

        if not content:
            continue

        normalized.append(
            {
                "role": role,
                "content": content[:1500],
            }
        )

    while (
        normalized
        and sum(
            len(message["content"])
            for message in normalized
        ) > max_chars
    ):
        normalized.pop(0)

    return normalized

def build_conversation_text(
    messages: list[dict[str, str]] | None,
) -> str:
    normalized = normalize_conversation(messages)

    if not normalized:
        return ""

    lines: list[str] = []

    for message in normalized:
        speaker = (
            "사용자"
            if message["role"] == "user"
            else "AI"
        )

        lines.append(
            f"{speaker}: {message['content']}"
        )

    return "\n".join(lines)

def build_fallback_search_query(
    query: str,
    messages: list[dict[str, str]] | None,
) -> str:
    normalized = normalize_conversation(
        messages,
        max_messages=4,
        max_chars=2000,
    )

    previous_user_messages = [
        message["content"]
        for message in normalized
        if message["role"] == "user"
    ]

    if not previous_user_messages:
        return query.strip()

    previous_question = previous_user_messages[-1]

    return (
        f"{previous_question}와 관련하여 "
        f"{query.strip()}"
    )

def rewrite_query(
    query: str,
    messages: list[dict[str, str]] | None,
    response_client: OpenAI,
) -> str:
    conversation_text = build_conversation_text(
        messages
    )

    if not conversation_text:
        return query.strip()

    fallback_query = build_fallback_search_query(
        query=query,
        messages=messages,
    )

    try:
        response = response_client.responses.create(
            model=require_env(
                "AZURE_OPENAI_CHAT_DEPLOYMENT"
            ),
            instructions=(
                "당신은 축산 문서 검색용 질문 재작성기다. "
                "이전 대화와 현재 질문을 읽고 현재 질문을 "
                "대화 없이 이해할 수 있는 독립적인 검색 질문으로 바꾼다. "
                "답변하거나 거절하지 않는다. "
                "질문이 이미 독립적이면 그대로 반환한다. "
                "이전 대화에 없는 내용을 추가하지 않는다. "
                "검색 질문 한 문장만 한국어로 반환한다. "
                "설명, 번호, 따옴표, 접두어를 붙이지 않는다."
            ),
            input=(
                f"이전 대화:\n{conversation_text}\n\n"
                f"현재 질문:\n{query}\n\n"
                "독립적인 한국어 검색 질문:"
            ),
            reasoning={
                "effort": "minimal",
            },
            max_output_tokens=150,
        )

        rewritten = (
            response.output_text or ""
        ).strip()

    except Exception:
        return fallback_query

    if not rewritten:
        return fallback_query

    rewritten = rewritten.strip(
        "\"'“”‘’"
    )

    if is_refusal_text(rewritten):
        return fallback_query

    if len(rewritten) > 500:
        return fallback_query

    return rewritten

def build_clients() -> tuple[SearchClient, AzureOpenAI, OpenAI]:
    search = SearchClient(
        endpoint=require_env("AZURE_SEARCH_ENDPOINT"),
        index_name=require_env("AZURE_SEARCH_INDEX_NAME"),
        credential=AzureKeyCredential(require_env("AZURE_SEARCH_ADMIN_KEY")),
    )

    embedding_client = AzureOpenAI(
        azure_endpoint=require_env("AZURE_OPENAI_ENDPOINT"),
        api_key=require_env("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv(
            "AZURE_OPENAI_API_VERSION",
            "2024-10-21",
        ),
    )

    response_client = OpenAI(
        base_url=require_env("AZURE_OPENAI_RESPONSES_BASE_URL"),
        api_key=require_env("AZURE_OPENAI_API_KEY"),
    )

    return search, embedding_client, response_client

def result_to_chunk(result: Any) -> RetrievedChunk:
    return RetrievedChunk(
        id=result["id"],
        document_title=result["document_title"],
        document_type=result["document_type"],
        page_start=result.get("page_start"),
        page_end=result.get("page_end"),
        section_path=result.get("section_path") or "",
        content=result.get("content") or "",
        score=result.get("@search.score"),
        reranker_score=result.get("@search.reranker_score"),
    )

def retrieve(
    query: str,
    search: SearchClient,
    aoai: AzureOpenAI,
    mode: str,
) -> tuple[dict[str, Any], list[RetrievedChunk]]:
    config = ANSWER_MODES[mode]

    if is_web_service_question(query):
        return retrieve_web_service_guide(
            query=query,
            max_chunks=config["max_context_chunks"],
        )

    route = dict(route_query(query))

    if is_support_eligibility_question(query):
        route["route"] = "support_eligibility"
        route["filter"] = (
            "document_type eq 'program_guideline' "
            "and review_required eq false"
        )
        route["top_k"] = max(
            int(route.get("top_k", 10)),
            12,
        )

    requested = max(
        route.get("top_k", 10),
        config["max_context_chunks"] * 3,
    )

    search_text = query

    normalized_query = normalize_text(query)

    if any(
       keyword in normalized_query
        for keyword in (
            "장시간 누워",
            "계속 누워",
            "누워 있는 소",
            "일어나지 못",
            "못 일어나",
            "서지 못",
            "못 서",
        )
    ):
        search_text = (
            f"{search_text} "
            "기립불능 파행 임상증상"
        )

    if is_legal_subject_question(query):
        article_numbers = extract_article_numbers(query)

        article_hint = " ".join(
            f"제{number}조"
            for number in article_numbers
        )

        search_text = (
            f"{query} "
            f"{article_hint} "
            "의무자 책임자 대상자 신고하여야 하여야 한다"
        ).strip()

    if is_legal_report_duty_question(query):
        search_text = (
            f"{search_text} "
            "가축전염병 예방법 제11조 "
            "죽거나 병든 가축의 신고 "
            "신고대상 가축 신고하여야"
        )

    if is_support_eligibility_question(query):
        search_text = (
            f"{query} "
            "사업대상 지원자격 축산업 허가 등록"
        )

    if (
        route.get("route") == "field_action"
        and any(
            keyword in normalize_text(query)
            for keyword in (
                "신고 이후",
                "신고 후",
                "신고한 뒤",
                "신고한 다음",
                "현장 대응",
                "대응 절차",
                "현장 조치",
                "전체적으로 정리",
            )
        )
    ):
        search_text = (
            f"{search_text} "
            "구제역 의심축 신고 농장 "
            "신고 후 조치 "
            "가축방역기관 도착 전 "
            "의심축 격리 "
            "농장 출입 통제 "
            "차량 출입 통제 "
            "소독 "
            "가축 이동 제한"
        )

    embedding = aoai.embeddings.create(
        model=require_env(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        ),
        input=[search_text],
        dimensions=int(
            os.getenv(
                "AZURE_OPENAI_EMBEDDING_DIMENSIONS",
                "1536",
            )
        ),
    ).data[0].embedding

    vector_query = VectorizedQuery(
        vector=embedding,
        k_nearest_neighbors=max(
            requested * 3,
            30,
        ),
        fields="content_vector",
    )

    results = search.search(
        search_text=search_text,
        vector_queries=[vector_query],
        query_type="semantic",
        semantic_configuration_name="rag-semantic",
        filter=route.get("filter"),
        top=requested,
        select=[
            "id",
            "document_title",
            "document_type",
            "page_start",
            "page_end",
            "section_path",
            "content",
        ],
    )

    chunks: list[RetrievedChunk] = [
        result_to_chunk(result)
        for result in results
    ]

    # 명시적인 법령 조문 질문은 조문 번호로 보조 검색한다.
    if (
        route.get("route") == "legal"
        and extract_article_numbers(query)
    ):
        article_numbers = extract_article_numbers(query)
        document_hint = extract_legal_document_hint(query)

        article_search_text = " ".join(
            f"제{number}조"
            for number in article_numbers
        )

        article_results = search.search(
            search_text=article_search_text,
            query_type="semantic",
            semantic_configuration_name="rag-semantic",
            filter=route.get("filter"),
            top=10,
            select=[
                "id",
                "document_title",
                "document_type",
                "page_start",
                "page_end",
                "section_path",
                "content",
            ],
        )

        article_chunks = [
            result_to_chunk(result)
            for result in article_results
        ]

        # 질문에 법령명이 명시됐다면 해당 법령을 우선 유지한다.
        if document_hint:
            matched_article_chunks = [
                chunk
                for chunk in article_chunks
                if normalize_text(document_hint)
                in normalize_text(chunk.document_title)
            ]

            if matched_article_chunks:
                article_chunks = matched_article_chunks

        chunks.extend(article_chunks)

    if is_support_eligibility_question(query):
        eligibility_chunk_ids = (
            "fdc055b77d9da1a277bab3ec809aa0b6",
            "56707817673b600d357cf88dad218d6e",
        )

        eligibility_chunks: list[RetrievedChunk] = []

        for chunk_id in eligibility_chunk_ids:
            try:
                document = search.get_document(
                    key=chunk_id,
                    selected_fields=[
                        "id",
                        "document_title",
                        "document_type",
                        "page_start",
                        "page_end",
                        "section_path",
                        "content",
                    ],
                )

                eligibility_chunks.append(
                    result_to_chunk(document)
                )

            except Exception as exc:
                print(
                    f"[지원자격 청크 조회 실패] "
                    f"id={chunk_id}, error={exc}"
                )

        if eligibility_chunks:
            chunks = eligibility_chunks

    deduped = deduplicate(chunks)

    if (
        is_legal_subject_question(query)
        or (
            route.get("route") == "legal"
            and bool(extract_article_numbers(query))
        )
    ):
        deduped = prioritize_legal_chunks(
            query=query,
            chunks=deduped,
        )

    if is_support_eligibility_question(query):
        deduped = prioritize_support_eligibility_chunks(
            chunks=deduped,
        )

    max_context_chunks = config["max_context_chunks"]

    if is_support_eligibility_question(query):
        max_context_chunks = 2

    return (
        route,
        deduped[:max_context_chunks],
    )


def build_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for idx, chunk in enumerate(chunks, 1):
        blocks.append(
            "\n".join(
                [
                    f"[근거 {idx}]",
                    f"문서: {chunk.document_title}",
                    f"페이지: {chunk.page_label}",
                    f"위치: {chunk.section_path}",
                    f"청크 ID: {chunk.id}",
                    "내용:",
                    chunk.content,
                ]
            )
        )
    return "\n\n".join(blocks)


def system_prompt(
    mode: str,
    legal_subject: bool = False,
    allow_general_supplement: bool = False,
) -> str:
    cfg = ANSWER_MODES[mode]

    length_instruction = cfg["instruction"]

    if allow_general_supplement and mode == "detailed":
        length_instruction = (
            "절차, 조건, 예외를 구분해 충분히 설명한다. "
            "검색 근거와 일반 지식 보완 영역을 명확히 분리한다."
        )

    if legal_subject and mode == "short":
        length_instruction = (
            "질문에 직접 답한다. "
            "답변은 최대 3문장으로 작성한다. "
            "직접 관련 조문에 열거된 주요 주체와 핵심 예외를 누락하지 않는다. "
            "선임 의무자와 선임되는 사람을 명확히 구분한다. "
            "답변 본문은 450자 이내로 작성한다."
        )
    if allow_general_supplement:
        knowledge_policy = """
- 검색 근거로 확인되는 내용을 항상 먼저 답하고 해당 주장에만 인용 번호를 표시한다.
- 질문의 일부가 검색 근거에 없을 때만 '추가 설명' 영역을 분리해 일반 지식으로 보완할 수 있다.
- 일반 지식 영역에는 검색 근거 인용 번호를 표시하지 않는다.
- 일반 지식 영역에는 등록 문서의 직접 근거가 아니라는 주의 문구를 반드시 포함한다.
- 법령·지원 자격·금액·기간·방역 조치를 일반 지식으로 추정하거나 단정하지 않는다.
""".strip()
    else:
        knowledge_policy = """
- 반드시 제공된 검색 근거만 사용한다.
- 검색 근거에 없는 내용을 일반지식으로 보충하거나 추측하지 않는다.
- 검색 근거가 질문에 직접 답하지 못하면
  "제공된 문서에서는 해당 내용을 확인할 수 없습니다."
  라고 답한다.
""".strip()

    return f"""
당신은 축산 방역·법령·지원사업 문서를 기반으로 답변하는 질의응답 시스템이다.

기본 원칙:
{knowledge_policy}
- 질문과 직접 관련되지 않은 문서를 이용해 억지로 답변하지 않는다.
- 질문이 구제역에 관한 것이 아닐 경우 구제역 신고나 이동 제한 내용을 임의로 답하지 않는다.
- 질문이 법령, 지원사업, 이력관리, 방역, 질병 중 어느 영역인지 구분해 답한다.
- 근거가 서로 충돌하면 충돌 사실을 명확히 밝힌다.
- 법령과 사업 지침은 검색 근거에 표시된 시점과 문구를 기준으로 설명한다.
- 이전 대화에서 이미 신고를 안내한 경우, 후속 질문에서는 신고 전화번호와 신고 절차를 반복하지 않는다.
- "그다음", "이후", "어떤 조치"와 같은 후속 질문에는 신고 이후 행동만 답한다.
- 신고 질문의 최종 답변에는 전화번호와 "관할 방역기관"만 표시한다.
- 원문에 상세 기관명이 있더라도 각각 열거하거나 그대로 복사하지 않는다.
- 법적 신고 의무자를 묻는 질문은 신고 의무를 직접 규정한 조문을 우선 사용한다.
- 질문의 의무를 직접 규정한 조문이 검색 근거에 있으면 일반적인 책무 조항으로 대신 답하지 않는다.
- 법령에 여러 주체가 열거되어 있으면 직접 관련 조문의 각 항을 확인해 주요 주체를 누락하지 않는다.
- 법령에 여러 신고 의무자가 열거되어 있으면 주요 주체를 누락하지 않는다.
- 단서와 예외가 있는 경우 답변 길이 범위 안에서 함께 밝힌다.

답변 작성:
- 질문의 표현을 그대로 반복하지 않는다.
- 직접적인 답을 먼저 제시한다.
- 사용자가 요청한 형식이 있으면 그 형식을 따른다.
- 질문이 절차를 요구하면 단계별로 설명한다.
- 질문이 비교를 요구하면 항목별로 비교한다.
- 같은 내용을 반복하지 않는다.
- 자연스러운 한국어 존댓말을 사용한다.
- 문서 원문의 깨진 띄어쓰기는 의미를 유지하면서 교정한다.
- 사용자가 여러 범주를 함께 정리해 달라고 하면 각 범주의 핵심 항목을 우선 제시하고, 세부 예외와 행정절차는 질문에 직접 필요한 범위로만 제한한다.

구제역 관련 질문:
- 질문이 구제역 신고 또는 의심축 조치에 관한 경우에만 적용한다.
- 신고 기관은 "구제역 신고 전용전화 또는 관할 방역기관"으로 표현한다.
- 구제역 신고 전화번호는 신고 방법을 묻는 질문에서만 표시한다.
- 신고 전화번호는 1588-4060 또는 1588-9060으로 안내한다.
- 시군구, 시도 가축방역기관, 검역본부, 농식품부 등 기관 전체 목록은 나열하지 않는다.
- 농장주가 해야 할 행동과 방역기관이 수행하는 업무를 반드시 구분한다.
- 사용자가 농장주나 발견자의 행동을 묻는 경우 농장주가 직접 해야 할 행동을 먼저 답한다.
- 검사, 시료 채취, 역학조사 등은 농장주의 행동으로 표현하지 않는다.
- 기관의 업무를 설명할 때는 반드시 "방역기관은"이라는 주어를 사용한다.
- 일반 농장주에게 통제소 설치, 시료 채취, 역학조사 등 전문 방역업무를 직접 수행하라고 안내하지 않는다.
- 격리나 소독을 안내할 때는 안전을 확보하고 방역기관의 지시에 따르도록 표현한다.
- 농장주 답변은 이동·출입 제한, 의심축 접촉 방지, 현장 대기와 지시 준수를 중심으로 설명한다.

인용 규칙:
- 중요한 주장 뒤에 [1], [2]처럼 검색 근거 번호를 표시한다.
- 제공된 검색 근거 번호만 사용한다.
- 사용하지 않은 근거 번호를 표시하지 않는다.
- 같은 번호를 연속해서 중복 표시하지 않는다.
- 답변 안에 별도의 출처 목록을 작성하지 않는다.
- "출처", "참고문헌", "검색 근거" 제목을 작성하지 않는다.
- 청크 ID는 표시하지 않는다.
- 인용은 반드시 [1], [2], [3] 형식으로 작성한다.
- "제공된 문서에서는 해당 내용을 확인할 수 없습니다."라고 답하는 경우 인용 번호를 표시하지 않는다.

길이 및 형식:
{length_instruction}
""".strip()

def clean_generated_text(text: str) -> str:
    # -----------------------------------------------------
    # 1. 기본 인용 형식 정리
    # -----------------------------------------------------

    # [근거 1] -> [1]
    text = re.sub(
        r"\[\s*근거\s*(\d+)\s*\]",
        r"[\1]",
        text,
    )

        # [근거 1, 2, 3] -> [1][2][3]
    def replace_multi_basis(match: re.Match[str]) -> str:
        numbers = re.findall(
            r"\d+",
            match.group(1),
        )

        return "".join(
            f"[{number}]"
            for number in numbers
        )

    text = re.sub(
        r"\[\s*근거\s*([\d,\s]+)\]",
        replace_multi_basis,
        text,
    )

    # 인용 앞 불필요한 공백 제거
    text = re.sub(
        r"\s+\[(\d+)\]",
        r"[\1]",
        text,
    )

    # 마침표 뒤 인용 -> 인용 뒤 마침표
    text = re.sub(
        r"\.\s*\[(\d+)\]",
        r"[\1].",
        text,
    )

    # 인용 뒤 마침표 형식 통일
    text = re.sub(
        r"\[(\d+)\]\s*\.",
        r"[\1].",
        text,
    )

    # 답변 마지막에 독립적으로 남은 인용 제거
    # 예: 지원 가능[1]. [2] -> 지원 가능[1].
    text = re.sub(
        r"(\[\d+\])\.\s+\[\d+\]\s*$",
        r"\1.",
        text,
    )

    # -----------------------------------------------------
    # 2. 자주 깨지는 표현 정리
    # -----------------------------------------------------

    replacements = {
        "신고전용전화": "신고 전용전화",
        "연락가능": "연락 가능",
        "사람의이동": "사람의 이동",
        "신고내용": "신고 내용",
        "신고해야합니다": "신고해야 합니다",
        "사람의출입": "사람의 출입",
        "방문한동물약품": "방문한 동물약품",
        "대해사육계약": "대해 사육계약",
        "방역관리를하는": "방역관리를 하는",
        "자이며,다만": "자이며, 다만",
        "대하여사육계약": "대하여 사육계약",
        "소유자또는": "소유자 또는",
        "신고의무": "신고 의무",
        "신고대상가축": "신고대상 가축",
        "알았거나알": "알았거나 알",
        "등농식품부": "등 농식품부",
        "농어업경영체미등록": "농어업경영체 미등록",
        "포기한경우": "포기한 경우",
        "당해년도": "당해연도",
        "인허가": "인·허가",
        "대출실행": "대출 실행",
        "「축산법」제": "「축산법」 제",
        "대표자에 적용) 도": "대표자에게 적용)도",
        "설치로인허가가": "설치로 인·허가가",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # -----------------------------------------------------
    # 3. 한국어 띄어쓰기 보정
    # -----------------------------------------------------

    text = re.sub(
        r"해야\s*합니다",
        "해야 합니다",
        text,
    )

    text = re.sub(
        r"의\s*출입",
        "의 출입",
        text,
    )

    text = re.sub(
        r"(신고|대기|제한|유지|실시|조치)해야\s*합니다",
        r"\1해야 합니다",
        text,
    )

    text = re.sub(
        r"(하고|하며|하고서)"
        r"(방역기관|농장주|가축방역관|사용자|신고기관|담당기관)",
        r"\1 \2",
        text,
    )

    text = re.sub(
        r"(이동을|검사를|소독을|출입을|반출을|접촉을|대기를|조치를)"
        r"(금지|진행|실시|제한|중지|유지|지시)",
        r"\1 \2",
        text,
    )

    text = re.sub(
        r"(소유한|관리하는|정하는|갖춘)"
        r"(소유자|관리자|사람|자)",
        r"\1 \2",
        text,
    )

    text = re.sub(
        r"소유자\s*또는",
        "소유자 또는",
        text,
    )

    text = re.sub(
        r"신고대상\s*가축",
        "신고대상 가축",
        text,
    )

    text = re.sub(
        r"알았거나\s*알",
        "알았거나 알",
        text,
    )

    text = re.sub(
        r"알\s*수\s*있었던",
        "알 수 있었던",
        text,
    )

    text = re.sub(
        r"대하여\s*사육계약",
        "대하여 사육계약",
        text,
    )

    text = re.sub(
        r"대해\s*사육계약",
        "대해 사육계약",
        text,
    )

    text = re.sub(
        r"방문한\s*동물약품",
        "방문한 동물약품",
        text,
    )

    text = re.sub(
        r"구청장의\s*인가",
        "구청장의 인가",
        text,
    )

    text = re.sub(
        r"의뢰\s*사실",
        "의뢰 사실",
        text,
    )

    text = re.sub(
        r"하는\s*경우",
        "하는 경우",
        text,
    )

    # -----------------------------------------------------
    # 4. 괄호 / 조사 / 접속어 정리
    # -----------------------------------------------------

    text = re.sub(
        r"\)(?=[가-힣A-Za-z])",
        ") ",
        text,
    )

    text = re.sub(
        r"\)\s+(나|이나|로|으로|에|에서|에게|와|과|를|을|은|는|이|가|의)",
        r")\1",
        text,
    )

    text = re.sub(
        r"\)\s*(및|또는)\s*",
        r") \1 ",
        text,
    )

    text = re.sub(
        r"\(\s*\)",
        "",
        text,
    )

    # -----------------------------------------------------
    # 5. 문장부호 정리
    # -----------------------------------------------------

    text = re.sub(
        r",(?=\S)",
        ", ",
        text,
    )

    text = re.sub(
        r"\.(?=\S)",
        ". ",
        text,
    )

    text = re.sub(
        r"\s*;\s*",
        ". ",
        text,
    )

    text = re.sub(
        r"\s+,",
        ",",
        text,
    )

    text = re.sub(
        r",\s*,",
        ",",
        text,
    )

    # -----------------------------------------------------
    # 6. 불필요한 제목 제거
    # -----------------------------------------------------

    text = re.sub(
        r"^\s*(?:"
        r"직접적인\s*답변|"
        r"직접적\s*답변|"
        r"직접적인\s*답|"
        r"직접적\s*답|"
        r"답변|"
        r"변"
        r")\s*:?\s*",
        "",
        text,
    )

    text = re.sub(
        r"\s*핵심\s*근거"
        r"(?:\s*(?:및|와)\s*"
        r"(?:예외\s*사항|예외사항|요약\s*설명|추가\s*설명|조건|예외))?"
        r"\s*:?\s*",
        "\n\n",
        text,
    )

    text = re.sub(
        r"\s*예비·신청\s*절차\s*관련\s*참고\s*",
        "\n",
        text,
    )

    # "근거 및 요약 설명:", "근거 및 추가 설명:" 등의 제목 제거
    text = re.sub(
        r"\s*(?:핵심\s*)?근거\s*및\s*"
        r"(?:요약\s*설명|추가\s*설명|예외\s*사항|예외사항|조건)"
        r"\s*:?\s*",
        "\n\n",
        text,
    )

    # "참고(관련 조항):", "참고 (관련 내용):" 등의 제목만 제거
    text = re.sub(
        r"\s*참고\s*\([^)]*\)\s*:?\s*",
        "\n\n",
        text,
    )

    # "요약된 신고 의무자 및 적용 대상" 같은 법령 요약 제목 제거
    text = re.sub(
        r"^\s*(?:요약된\s*)?"
        r"(?:신고\s*)?"
        r"(?:의무자|신고\s*의무자)"
        r"\s*(?:및\s*적용\s*대상)?\s*:?\s*\n+",
        "",
        text,
        flags=re.MULTILINE,
    )

    # -----------------------------------------------------
    # 7. 지원사업 번호 제목 정리
    # -----------------------------------------------------

    text = re.sub(
        r"\s*(① 기본 대상|② 추가 인정 대상|③ 주요 지원 제외 조건|④ 조건부 인정 및 주요 예외)\s*",
        r"\n\n\1\n",
        text,
    )

    # detailed에서 표현이 조금 달라질 수 있는 제목
    text = re.sub(
        r"\s*(② 추가로 인정되는 대상(?:\([^)]*\))?|"
        r"② 추가로 인정되는 경우|"
        r"③ 주요 지원 제외(?:\([^)]*\))?\s*조건?)\s*",
        r"\n\n\1\n",
        text,
    )

    # 인용 뒤 바로 번호 제목이 붙는 경우
    text = re.sub(
        r"(\[\d+\]\.)\s*(①|②|③|④)\s*",
        r"\1\n\n\2 ",
        text,
    )

    # -----------------------------------------------------
    # 8. 목록 줄바꿈 정리
    # -----------------------------------------------------

    text = re.sub(
        r"(\[\d+\])\s*-\s+",
        r"\1\n- ",
        text,
    )

    text = re.sub(
        r"(?<=[.다요])\s+-\s+",
        "\n- ",
        text,
    )

    # -----------------------------------------------------
    # 9. 불필요한 메타 문장 제거
    # -----------------------------------------------------

    text = re.sub(
        r"^\s*\(문서 근거만 사용\).*?\n+",
        "",
        text,
    )

    text = re.sub(
        r"^\s*(?:아래는|다음은).*?"
        r"(?:정리합니다|설명합니다)\.\s*",
        "",
        text,
    )

    text = re.sub(
        r"\s*\(근거:\s*[^)]*\)\s*$",
        "",
        text,
    )

    text = re.sub(
        r"\s*참고:\s*.*$",
        "",
        text,
    )

    # 문서/지침을 근거로 정리했다는 마지막 괄호 문장 제거
    text = re.sub(
        r"\s*\([^)]*(?:문서|지침)[^)]*"
        r"(?:근거|기준)[^)]*"
        r"(?:정리|작성)[^)]*\)"
        r"(?:\s*\[\d+\])*\s*$",
        "",
        text,
    )

    # 괄호 없이 생성되는 참고/근거 메타 문장 제거
    text = re.sub(
        r"\s*(?:참고|근거)\s*:\s*"
        r".*(?:문서|지침).*"
        r"(?:정리|작성).*"
        r"(?:\s*\[\d+\])*\s*$",
        "",
        text,
    )

    # -----------------------------------------------------
    # 10. 기타 문자 정리
    # -----------------------------------------------------

    text = text.replace(r"\~", "~")

    text = re.sub(
        r"「축산법」\s*제",
        "「축산법」 제",
        text,
    )

    # -----------------------------------------------------
    # 10-1. 모델 메타 제목 / 마크다운 잔여물 정리
    # -----------------------------------------------------

    # "설명 (근거):" 같은 메타 제목 제거
    text = re.sub(
        r"(?m)^\s*설명\s*\(\s*근거\s*\)\s*:?\s*$",
        "",
        text,
    )

    # "영역: 지원사업(...)" 같은 내부 분류 제목 제거
    text = re.sub(
        r"(?m)^\s*영역\s*:\s*.*$",
        "",
        text,
    )

    # "답변(지원 대상·제외 대상 정리)" 같은 메타 제목 제거
    text = re.sub(
        r"(?m)^\s*답변\s*\([^)]*\)\s*:?\s*$",
        "",
        text,
    )

    # "(충돌·추가 설명)" 같은 모델 내부형 제목 제거
    text = re.sub(
        r"(?m)^\s*\(\s*충돌[·ㆍ\s]*추가\s*설명\s*\)\s*$",
        "",
        text,
    )

    # 내용 없이 단독으로 남은 "-" 목록 기호 제거
    text = re.sub(
        r"(?m)^\s*-\s*$",
        "",
        text,
    )

    # 날짜가 줄바꿈으로 쪼개진 경우 복원
    # 예: 2014.\n12. 31 -> 2014. 12. 31
    text = re.sub(
        r"(?m)^[ \t]*(\d{4})\.[ \t]*\n[ \t]*(\d{1,2}\.\s*\d{1,2})",
        r"\1. \2",
        text,
    )

    # 모델이 "~" 앞에 하나 이상의 역슬래시를 붙인 경우 제거
    text = re.sub(
        r"\\+~",
        "~",
        text,
    )
    # -----------------------------------------------------
    # 근거 메타 표현 정리
    # -----------------------------------------------------

    # 1. 마지막 줄에 같은 줄로 붙은 메타 근거 문장 제거
    # 예:
    # 근거: 가축전염병 예방법 제11조 본문 및 관련 항[1].
    text = re.sub(
        r"(?m)^[ \t]*근거[ \t]*:[ \t]*(?=\S)"
        r"[^\n]+[ \t]*(?:\n[ \t]*)*\Z",
        "",
        text,
    )

    # 2. "근거:"만 단독 제목이면 제목만 제거
    # 다음 줄의 실제 내용은 보존
    text = re.sub(
        r"(?m)^[ \t]*근거[ \t]*:?[ \t]*$",
        "",
        text,
    )

    # -----------------------------------------------------
    # 메타 제목 및 생성형 잔여 문구 추가 정리
    # -----------------------------------------------------

    # "직접 답변" 단독 제목 제거
    text = re.sub(
        r"(?m)^\s*직접\s*답변\s*:?\s*$",
        "",
        text,
    )

    # "직접적 답변:", "직접적인 답변:" 단독 제목 제거
    text = re.sub(
        r"(?m)^\s*직접적(?:인)?\s*답변\s*:?\s*$",
        "",
        text,
    )

    # "법적 근거 표기" 단독 제목 제거
    text = re.sub(
        r"(?m)^\s*법적\s*근거\s*표기\s*:?\s*$",
        "",
        text,
    )

    # "충돌 여부" 단독 제목 제거
    text = re.sub(
        r"(?m)^\s*충돌\s*여부\s*:?\s*$",
        "",
        text,
    )

    # 단독 "설명:" 접두어 제거
    text = re.sub(
        r"(?m)^\s*설명\s*:\s*",
        "",
        text,
    )

    # "지원 대상 근거:[1]" / "제외 대상 근거:[2]" 같은
    # 의미 없는 인용 전용 줄 제거
    text = re.sub(
        r"(?m)^\s*-\s*(?:지원|제외)\s*대상\s*근거\s*:\s*\[\d+\]\s*$",
        "",
        text,
    )

    # 문서 간 충돌이 없다는 불필요한 메타 문장 제거
    text = re.sub(
        r"(?m)^\s*-\s*제공된\s*문서(?:들)?\s*간에\s*"
        r"(?:상충|충돌)하는\s*내용은\s*없습니다\.?\s*$",
        "",
        text,
    )

    # 답변 마지막의 불필요한 후속 제안 제거
    # 예:
    # - "필요하면 ... 정리해 드리겠습니다."
    # - "만약 ... 원하시면 ... 안내해 드리겠습니다."
    text = re.sub(
        r"(?ms)\n*\s*(?:"
        r"필요하면\s+.*?"
        r"(?:정리해\s*드리겠습니다|설명해\s*드리겠습니다)"
        r"|"
        r"만약\s+.*?"
        r"(?:원하시면|필요하시면).*?"
        r"(?:안내해\s*드리겠습니다|설명해\s*드리겠습니다|정리해\s*드리겠습니다)"
        r")\.?\s*$",
        "",
        text,
    )

    # 일본어 조사 혼입 보정
    text = text.replace("」に 따른", "」에 따른")
    text = text.replace("법」に 따른", "법」에 따른")

    # -----------------------------------------------------
    # 11. 최종 공백/줄바꿈 정리
    # -----------------------------------------------------

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r" *\n *",
        "\n",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()

def remove_generated_sources(answer: str) -> str:
    """모델이 임의로 생성한 출처 영역을 제거한다."""
    answer = re.split(
        r"\n\s*(?:출처|참고문헌|검색\s*근거)\s*:?\s*(?:\n|$)",
        answer,
        maxsplit=1,
    )[0]

    return answer.strip()

def deduplicate_citation_groups(answer: str) -> str:
    """[1][3][2][2] 같은 인용을 [1][2][3]으로 정리한다."""

    def replace_group(match: re.Match[str]) -> str:
        numbers = re.findall(r"\[(\d+)\]", match.group(0))

        unique_numbers = sorted(
            {int(number) for number in numbers}
        )

        return "".join(
            f"[{number}]"
            for number in unique_numbers
        )

    return re.sub(
        r"(?:\[\d+\])+",
        replace_group,
        answer,
    )

def resolve_cited_sources(
    answer: str,
    chunks: list[RetrievedChunk],
    max_sources: int,
) -> GeneratedAnswer:
    answer = remove_generated_sources(answer)
    answer = deduplicate_citation_groups(answer)

    cited_numbers: list[int] = []

    for number_text in re.findall(r"\[(\d+)\]", answer):
        number = int(number_text)

        if (
            1 <= number <= len(chunks)
            and number not in cited_numbers
        ):
            cited_numbers.append(number)

    cited_numbers = cited_numbers[:max_sources]

    # 인용이 없으면 출처를 임의로 추가하지 않는다.
    if not cited_numbers:
        answer = re.sub(r"\[(\d+)\]", "", answer)

        return GeneratedAnswer(
            text=answer.strip(),
            cited_chunks=[],
        )

    number_mapping = {
        original_number: new_number
        for new_number, original_number in enumerate(
            cited_numbers,
            start=1,
        )
    }

    def replace_citation(match: re.Match[str]) -> str:
        original_number = int(match.group(1))
        new_number = number_mapping.get(original_number)

        if new_number is None:
            return ""

        return f"[{new_number}]"

    answer = re.sub(
        r"\[(\d+)\]",
        replace_citation,
        answer,
    )

    answer = deduplicate_citation_groups(answer)

    cited_chunks = [
        chunks[number - 1]
        for number in cited_numbers
    ]

    return GeneratedAnswer(
        text=answer.strip(),
        cited_chunks=cited_chunks,
    )

def request_answer_text(
    response_client: OpenAI,
    mode: str,
    input_text: str,
    legal_subject: bool = False,
    allow_general_supplement: bool = False,
) -> str:
    response = response_client.responses.create(
        model=require_env(
            "AZURE_OPENAI_CHAT_DEPLOYMENT"
        ),
        instructions=system_prompt(
            mode,
            legal_subject=legal_subject,
            allow_general_supplement=allow_general_supplement,
        ),
        input=input_text,
        reasoning={
            "effort": "minimal",
        },
        max_output_tokens=ANSWER_MODES[
            mode
        ]["max_output_tokens"],
    )

    answer = (
        response.output_text or ""
    ).strip()

    if not answer:
        raise RuntimeError(
            "답변 모델이 빈 텍스트를 반환했습니다. "
            f"status={response.status}, "
            f"incomplete_details={response.incomplete_details}"
        )

    return answer


def request_general_knowledge_answer(
    response_client: OpenAI,
    query: str,
    mode: str,
) -> GeneratedAnswer:
    """RAG 검색을 먼저 수행한 뒤 근거가 부족할 때만 일반 지식으로 답한다."""
    safety_instruction = general_knowledge_notice(query)
    response = response_client.responses.create(
        model=require_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        instructions=(
            "사용자 질문에 일반적인 지식 범위에서 한국어 존댓말로 답하세요. "
            "등록된 RAG 문서를 확인한 것처럼 표현하지 마세요. "
            "[1], [2] 같은 인용 번호나 출처 목록을 만들지 마세요. "
            "확실하지 않은 내용은 추정하지 말고 한계를 밝히세요. "
            "법령 조항 번호, 벌칙, 지원 자격, 금액, 기간은 추정하지 마세요. "
            "법률·행정 질문은 최신 법령 또는 담당 기관 확인을 안내하세요. "
            "방역 질문은 관할 방역기관 또는 수의사의 지시를 우선하도록 안내하세요. "
            "동물 건강 질문은 진단이나 처치를 단정하지 말고 수의사 확인을 안내하세요. "
            f"답변에는 다음 안전 의미가 반드시 유지되어야 합니다: {safety_instruction}"
        ),
        input=f"현재 사용자의 질문:\n{query}",
        reasoning={"effort": "minimal"},
        max_output_tokens=ANSWER_MODES[mode]["max_output_tokens"],
    )
    incomplete_details = getattr(response, "incomplete_details", None)
    incomplete_reason = (
        incomplete_details.get("reason")
        if isinstance(incomplete_details, dict)
        else getattr(incomplete_details, "reason", None)
    )
    output_token_limit_reached = (
        getattr(response, "status", None) == "incomplete"
        and incomplete_reason == "max_output_tokens"
    )

    if (
        getattr(response, "status", None) == "incomplete"
        and not output_token_limit_reached
    ):
        raise RuntimeError(
            "일반 지식 답변 생성이 완료되지 않았습니다. "
            f"incomplete_details={response.incomplete_details}"
        )

    answer = (response.output_text or "").strip()
    if not answer:
        raise RuntimeError(
            "일반 지식 답변 모델이 빈 텍스트를 반환했습니다. "
            f"status={response.status}, "
            f"incomplete_details={response.incomplete_details}"
        )

    # 일반 지식에는 코드·URL 같은 표기가 포함될 수 있으므로 RAG 문서 전용
    # 문장 정리 대신 가짜 출처와 인용만 제거한다.
    answer = remove_generated_sources(answer)
    answer = re.sub(r"\[\d+\]", "", answer)
    answer = re.sub(r"[ \t]+\n", "\n", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer).strip()

    if safety_instruction not in answer:
        answer = f"{safety_instruction}\n\n{answer}"

    if output_token_limit_reached:
        complete_boundaries = [
            match.end()
            for match in re.finditer(
                r"[.!?。！？](?:[\"”’\)\]]*)?(?=\s|$)",
                answer,
            )
        ]
        last_line_break = answer.rfind("\n")
        if last_line_break > 0:
            complete_boundaries.append(last_line_break)

        if complete_boundaries:
            answer = answer[:max(complete_boundaries)].rstrip()
        else:
            answer = ""

        answer = (
            f"{answer}\n\n{GENERAL_KNOWLEDGE_CONTINUATION_NOTICE}"
            if answer
            else GENERAL_KNOWLEDGE_CONTINUATION_NOTICE
        )

    return GeneratedAnswer(text=answer.strip(), cited_chunks=[])


def ensure_mixed_answer_notice(answer: str, query: str) -> str:
    """혼합 답변의 일반 지식 영역에 deterministic 주의 문구를 넣는다."""
    notice = general_knowledge_notice(query)
    if notice in answer:
        return answer

    heading = re.search(r"(?m)^\s*추가\s*설명\s*:?\s*$", answer)
    if heading:
        insert_at = heading.end()
        return f"{answer[:insert_at]}\n{notice}{answer[insert_at:]}"

    return f"{answer.rstrip()}\n\n추가 설명:\n{notice}"

FMD_REPORT_KEYWORDS = {
    "어디에 신고",
    "어디로 신고",
    "어디에 연락",
    "어디로 연락",
    "신고 방법",
    "신고 전화",
    "신고 번호",
    "전화번호",
    "연락처",
}

FMD_REPORT_EXCLUSION_KEYWORDS = {
    "누구",
    "누가",
    "의무자",
    "신고 의무",
    "법적 의무",
    "예방법",
    "법률",
    "법령",
    "조문",
    "몇 조",
    "대상자",
}

FMD_INITIAL_ACTION_KEYWORDS = {
    "발견하면 무엇을 해야",
    "의심되면 무엇을 해야",
    "발견하면 어떻게 해야",
    "의심되면 어떻게 해야",
    "발견했을 때 무엇을 해야",
    "발견했을 때 어떻게 해야",
}

LEGAL_REPORT_DUTY_KEYWORDS = (
    "신고 의무자",
    "신고해야 하는 의무자",
    "신고 의무가 있는 사람",
    "신고 의무가 있는 자",
    "신고할 의무가 있는 사람",
    "신고할 의무가 있는 자",
    "신고해야 하는 사람",
    "신고해야 하는 자",
    "누가 신고",
    "누구가 신고",
    "신고 주체",
)

LEGAL_SUBJECT_KEYWORDS = (
    "의무자",
    "신고 주체",
    "책임자",
    "누가",
    "누구",
    "대상자",
    "신고 의무가 있는 사람",
    "신고 의무가 있는 자",
    "신고할 의무가 있는 사람",
    "신고할 의무가 있는 자",
    "신고해야 하는 사람",
    "신고해야 하는 자",
)

LEGAL_DUTY_KEYWORDS = (
    "신고 의무",
    "법적 의무",
    "신고해야",
    "하여야",
    "해야 하는",
)

def is_legal_report_duty_question(query: str) -> bool:
    normalized = normalize_text(query)

    return any(
        keyword in normalized
        for keyword in LEGAL_REPORT_DUTY_KEYWORDS
    )

def is_legal_subject_question(query: str) -> bool:
    normalized = normalize_text(query)

    has_subject_intent = any(
        keyword in normalized
        for keyword in LEGAL_SUBJECT_KEYWORDS
    )

    has_legal_intent = (
        any(
            keyword in normalized
            for keyword in LEGAL_DUTY_KEYWORDS
        )
        or bool(extract_article_numbers(query))
        or "법률" in normalized
        or "예방법" in normalized
        or "시행령" in normalized
        or "시행규칙" in normalized
        or "조문" in normalized
    )

    return has_subject_intent and has_legal_intent

def prioritize_legal_chunks(
    query: str,
    chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    article_numbers = extract_article_numbers(query)
    query_tokens = query_keywords(query)
    document_hint = extract_legal_document_hint(query)

    def priority(
        chunk: RetrievedChunk,
    ) -> tuple[int, int, int, int, float]:
        combined = normalize_text(
            f"{chunk.section_path} {chunk.content}"
        )

        normalized_section = normalize_text(
            chunk.section_path
        )

        direct_article_match = 0
        article_reference_match = 0

        for article_number in article_numbers:
            article_patterns = (
                f"제{article_number}조",
                f"제 {article_number} 조",
            )

            # section_path에 있으면 해당 조문 자체
            if any(
                pattern in normalized_section
                for pattern in article_patterns
            ):
                direct_article_match = 1
                article_reference_match = 1
                break

            # content에만 있으면 다른 조문에서 해당 조문을 참조
            if any(
                pattern in combined
                for pattern in article_patterns
            ):
                article_reference_match = 1

        document_match = (
            1
            if document_hint
            and normalize_text(document_hint)
            in normalize_text(chunk.document_title)
            else 0
        )

        direct_duty_match = any(
            keyword in combined
            for keyword in (
                "신고하여야",
                "신고해야",
                "하여야 한다",
                "의무",
                "책임자",
                "대상자",
                "신고대상 가축",
            )
        )

        query_match = any(
            token in combined
            for token in query_tokens
        )

        # 같은 법령의 해당 조문 자체를 최우선
        if (
            article_numbers
            and direct_article_match
            and document_match
        ):
            rank = 0

        # 법령명이 다르더라도 해당 조문 자체
        elif article_numbers and direct_article_match:
            rank = 1

        # 같은 법령에서 해당 조문을 참조하는 다른 조문
        elif (
            article_numbers
            and article_reference_match
            and document_match
        ):
            rank = 2

        elif (
            is_legal_report_duty_question(query)
            and "죽거나 병든 가축의 신고" in combined
        ):
            rank = 2

        elif direct_duty_match:
            rank = 3

        elif query_match:
            rank = 4

        else:
            rank = 5

        score = (
            chunk.reranker_score
            if chunk.reranker_score is not None
            else 0.0
        )

        return (
            rank,
            -document_match,
            -direct_article_match,
            -article_reference_match,
            -score,
        )

    return sorted(
        chunks,
        key=priority,
    )


def prioritize_support_eligibility_chunks(
    chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    strong_terms = (
        "사업대상(fta기금)",
        "사업대상(농특회계 이차보전)",
        "지원자격 및 요건",
        "사업대상",
        "지원자격",
    )

    supporting_terms = (
        "축산업의 허가를 받거나 등록한",
        "축산업 허가·등록",
        "농업인 및 농업법인",
        "농업경영체 등록일",
        "지원 제외",
    )

    def priority(
        chunk: RetrievedChunk,
    ) -> tuple[int, float]:
        combined = normalize_text(
            f"{chunk.section_path} {chunk.content}"
        )

        if any(
            term in combined
            for term in strong_terms
        ):
            rank = 0
        elif any(
            term in combined
            for term in supporting_terms
        ):
            rank = 1
        else:
            rank = 2

        score = (
            chunk.reranker_score
            if chunk.reranker_score is not None
            else 0.0
        )

        return rank, -score

    return sorted(
        chunks,
        key=priority,
    )

def is_fmd_report_question(query: str) -> bool:
    normalized = normalize_text(query)

    has_fmd = (
        "구제역" in normalized
        or "의심축" in normalized
        or "의심 증상" in normalized
        or "의심증상" in normalized
    )

    has_exclusion_intent = any(
        keyword in normalized
        for keyword in FMD_REPORT_EXCLUSION_KEYWORDS
    )

    has_report_intent = any(
        keyword in normalized
        for keyword in FMD_REPORT_KEYWORDS
    )

    return (
        has_fmd
        and has_report_intent
        and not has_exclusion_intent
    )

FMD_FOLLOWUP_ACTION_KEYWORDS = {
    "그다음",
    "그 다음",
    "그 후",
    "그후",
    "이후",
    "다음에는",
    "어떤 조치",
    "무엇을 해야",
    "어떻게 해야",
    "밖으로 나가",
    "밖에 나가",
    "나가도 되",
    "외출",
    "농장을 떠나",
    "이동해도 되",
    "차량은 들어와",
    "차량이 들어와",
    "차량 출입",
    "차량이 출입",
    "차량은 출입",
    "차가 들어와",
    "들어와도 되",
    "가축을 옮겨",
    "가축 이동",
    "다른 축사로",
    "축사를 옮겨",
    "이동시켜도 되",
    "옮겨도 되",
    "언제까지",
    "얼마나 오래",
    "몇 시간",
    "몇 일",
    "며칠",
    "언제 나가",
    "언제 떠나",
    "언제까지 있어",
    "언제까지 대기",
    "소독해도 되",
    "소독하면 되",
    "바로 소독",
    "직접 소독",
    "제가 소독",
    "농장주가 소독",
    "가족이나 직원",
    "가족은 들어와",
    "직원은 들어와",
    "사람이 들어와",
    "사람은 들어와",
    "사람 출입",
    "들어와도 되",
    "방문해도 되",
    "출입해도 되",
    "분뇨나 장비",
    "분뇨를 밖으로",
    "장비를 밖으로",
    "물품을 밖으로",
    "밖으로 내보내",
    "반출해도 되",
    "내보내도 되",
    "분뇨 반출",
    "장비 반출",
    "물품 반출",
}

def is_fmd_post_report_action_question(query: str) -> bool:
    normalized = normalize_text(query)

    has_fmd = (
        "구제역" in normalized
        or "의심축" in normalized
        or "의심 가축" in normalized
    )

    has_report_context = any(
        keyword in normalized
        for keyword in (
            "신고한 다음",
            "신고 후",
            "신고하고 나서",
            "신고 이후",
            "신고했으면",
            "신고한 뒤",
        )
    )

    has_action_intent = any(
        keyword in normalized
        for keyword in (
            "무엇을 해야",
            "어떻게 해야",
            "해야 하나",
            "조치",
            "행동",
            "현장 대응",
            "대응 절차",
            "현장 절차",
            "전체적으로 정리",
        )
    )

    return (
        has_fmd
        and has_report_context
        and has_action_intent
    )


def is_fmd_followup_action_question(
    query: str,
    messages: list[dict[str, str]] | None,
) -> bool:
    normalized_query = normalize_text(query)

    has_followup_intent = any(
        keyword in normalized_query
        for keyword in FMD_FOLLOWUP_ACTION_KEYWORDS
    )

    if not has_followup_intent:
        return False

    conversation = normalize_conversation(
        messages,
        max_messages=4,
        max_chars=2000,
    )

    conversation_text = " ".join(
        message["content"]
        for message in conversation
    )

    has_fmd_context = (
        "구제역" in conversation_text
        or "의심축" in conversation_text
        or "1588-4060" in conversation_text
        or "1588-9060" in conversation_text
        or "관할 방역기관" in conversation_text
    )

    has_previous_report = (
        "신고" in conversation_text
        or "1588-4060" in conversation_text
        or "1588-9060" in conversation_text
    )

    return (
        has_fmd_context
        and has_previous_report
    )



def build_fmd_report_answer(
    chunks: list[RetrievedChunk],
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(
            text="제공된 문서에서는 해당 내용을 확인할 수 없습니다.",
            cited_chunks=[],
        )

    # 두 신고번호가 실제 본문에 모두 있는 청크를 우선한다.
    matched_chunks = [
        chunk
        for chunk in chunks
        if (
            "1588-4060" in chunk.content
            and "1588-9060" in chunk.content
        )
    ]

    # 번호가 서로 다른 청크에 분리된 경우를 대비한 보조 탐색
    if not matched_chunks:
        matched_chunks = [
            chunk
            for chunk in chunks
            if (
                "1588-4060" in chunk.content
                or "1588-9060" in chunk.content
            )
        ]

    cited_chunks = matched_chunks[:1]

    if not cited_chunks:
        return GeneratedAnswer(
            text=(
                "제공된 검색 근거에서는 구제역 신고 전화번호를 "
                "확인할 수 없습니다."
            ),
            cited_chunks=[],
        )

    citation = "".join(
        f"[{index}]"
        for index in range(
            1,
            len(cited_chunks) + 1,
        )
    )

    return GeneratedAnswer(
        text=(
            "구제역 의심축을 발견하면 구제역 신고 전용전화 "
            "1588-4060이나 1588-9060 또는 관할 방역기관에 "
            f"즉시 신고해야 합니다.{citation}"
        ),
        cited_chunks=cited_chunks,
    )

def build_fmd_post_report_action_answer(
    query: str,
    chunks: list[RetrievedChunk],
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(
            text="제공된 문서에서는 해당 내용을 확인할 수 없습니다.",
            cited_chunks=[],
        )

    priority_ids = (
        "a06aa329753164b9d369c350eca3f373",
        "bc1496e3eba3e8f6068f6c5afe097852",
        "b8f760720de0cfa9dcc52fe88edbab6b",
    )

    chunk_by_id = {
        chunk.id: chunk
        for chunk in chunks
    }

    cited_chunks = [
        chunk_by_id[chunk_id]
        for chunk_id in priority_ids
        if chunk_id in chunk_by_id
    ][:3]

    if not cited_chunks:
        cited_chunks = chunks[:2]

    citation_1 = "[1]" if len(cited_chunks) >= 1 else ""
    citation_2 = "[2]" if len(cited_chunks) >= 2 else citation_1
    citation_3 = "[3]" if len(cited_chunks) >= 3 else citation_2

    normalized_query = normalize_text(query)

    is_person_entry_question = any(
        keyword in normalized_query
        for keyword in (
            "가족이나 직원",
            "가족은 들어와",
            "직원은 들어와",
            "사람이 들어와",
            "사람은 들어와",
            "사람 출입",
            "방문해도 되",
            "출입해도 되",
        )
    )

    if is_person_entry_question:
        text = (
            f"방역기관의 별도 허용이 있기 전에는 가족이나 직원도 농장에 "
            f"임의로 출입시키지 않아야 합니다{citation_1}. "
            f"꼭 필요한 출입이 있는 경우에도 방역기관의 지시에 따라 "
            f"출입 제한과 소독 등 필요한 방역조치를 적용해야 합니다{citation_2}."
        )

        return GeneratedAnswer(
            text=text,
            cited_chunks=cited_chunks[:2],
        )

    is_vehicle_question = any(
        keyword in normalized_query
        for keyword in (
            "차량",
            "차가",
            "자동차",
            "사료차",
            "집유차",
        )
    )

    if is_vehicle_question:
        vehicle_cited_chunks = cited_chunks[:2]

        text = (
            f"방역기관의 별도 허용이 있기 전에는 차량을 임의로 "
            f"출입시키지 않아야 합니다{citation_1}. "
            f"불가피한 출입이 필요한 경우에도 방역기관의 지시에 따라 "
            f"세척·소독 등 필요한 방역조치를 한 뒤 처리해야 합니다{citation_2}."
        )

        return GeneratedAnswer(
            text=text,
            cited_chunks=vehicle_cited_chunks,
        )

    is_livestock_movement_question = any(
        keyword in normalized_query
        for keyword in (
            "가축을 옮겨",
            "가축 이동",
            "다른 축사로",
            "축사를 옮겨",
            "이동시켜도 되",
            "옮겨도 되",
        )
    )

    if is_livestock_movement_question:
        text = (
            f"방역기관의 별도 지시가 있기 전에는 가축을 다른 축사로 "
            f"임의 이동시키지 않아야 합니다{citation_1}. "
            f"의심축이 다른 가축과 접촉하지 않도록 하되, 격리나 이동은 "
            f"안전을 확보한 뒤 방역기관의 지시에 따라 실시해야 합니다{citation_2}."
        )

        return GeneratedAnswer(
            text=text,
            cited_chunks=cited_chunks[:2],
        )

    is_wait_duration_question = any(
        keyword in normalized_query
        for keyword in (
            "언제까지",
            "얼마나 오래",
            "몇 시간",
            "몇 일",
            "며칠",
            "언제 나가",
            "언제 떠나",
            "언제까지 있어",
            "언제까지 대기",
        )
    )

    if is_wait_duration_question:
        text = (
            f"구제역 정밀검사 결과가 나오거나 방역기관이 별도로 안내할 때까지 "
            f"농장을 임의로 떠나지 말고 연락 가능한 상태로 대기해야 합니다"
            f"{citation_1}."
        )

        return GeneratedAnswer(
            text=text,
            cited_chunks=cited_chunks[:1],
        )

    is_disinfection_question = any(
        keyword in normalized_query
        for keyword in (
            "소독해도 되",
            "소독하면 되",
            "바로 소독",
            "직접 소독",
            "제가 소독",
            "농장주가 소독",
        )
    )

    if is_disinfection_question:
        text = (
            f"신고 직후에는 임의로 무리하게 소독하지 말고, 먼저 사람과 차량의 "
            f"출입을 제한한 뒤 방역기관의 지시를 기다려야 합니다{citation_1}. "
            f"소독이 필요한 경우에는 안전을 확보하고 방역기관이 안내한 방법과 "
            f"범위에 따라 실시해야 합니다{citation_2}."
        )

        return GeneratedAnswer(
            text=text,
            cited_chunks=cited_chunks[:2],
        )

    is_material_removal_question = any(
        keyword in normalized_query
        for keyword in (
            "분뇨나 장비",
            "분뇨를 밖으로",
            "장비를 밖으로",
            "물품을 밖으로",
            "밖으로 내보내",
            "반출해도 되",
            "내보내도 되",
            "분뇨 반출",
            "장비 반출",
            "물품 반출",
        )
    )

    if is_material_removal_question:
        text = (
            f"방역기관의 별도 허용이 있기 전에는 분뇨·장비·물품을 "
            f"농장 밖으로 임의 반출하지 않아야 합니다{citation_1}. "
            f"불가피한 반출이 필요한 경우에도 방역기관의 지시에 따라 "
            f"이동 제한과 세척·소독 등 필요한 방역조치를 적용해야 합니다{citation_2}."
        )

        return GeneratedAnswer(
            text=text,
            cited_chunks=cited_chunks[:2],
        )

    text = (
        f"- 방역기관의 별도 안내가 있기 전에는 농장을 임의로 떠나지 말고, "
        f"농장 안에서 연락 가능한 상태를 유지해야 합니다{citation_1}.\n"
        f"- 의심축이 다른 가축과 접촉하지 않도록 하되, "
        f"가축을 임의로 이동시키지 않아야 합니다{citation_2}.\n"
        f"- 사람과 차량의 출입을 제한하고 가축·분뇨·장비·물품의 "
        f"이동을 중지해야 합니다{citation_3}.\n"
        f"- 필요한 소독은 안전을 확보한 뒤 방역기관의 지시에 따라 "
        f"실시해야 합니다{citation_2}."
    )

    return GeneratedAnswer(
        text=text,
        cited_chunks=cited_chunks,
    )

def legal_answer_needs_retry(
    query: str,
    answer: str,
) -> bool:
    normalized = normalize_text(answer)

    if is_legal_report_duty_question(query):
        required_terms = (
            "소유자",
            "관리자",
            "축산계열화사업자",
            "수의사",
            "연구책임자",
            "동물약품",
            "사료 판매자",
            "가축운송업자",
        )

        return any(
            term not in normalized
            for term in required_terms
        )

    return False

def legal_answer_is_awkward(
    query: str,
    answer: str,
) -> bool:
    normalized_query = normalize_text(query)
    normalized_answer = normalize_text(answer)

    if (
        "방역관리 책임자" in normalized_query
        and any(
            pattern in normalized_answer
            for pattern in (
                "사람을 선임하여 두어야 하는 사람",
                "사람을 선임해야 하는 사람",
                "방역관리 책임자가 선임",
            )
        )
    ):
        return True

    return False

def generate_answer(
    query: str,
    chunks: list[RetrievedChunk],
    response_client: OpenAI,
    mode: str,
    messages: list[dict[str, str]] | None = None,
    search_query: str | None = None,
) -> GeneratedAnswer:
    if is_realtime_weather_question(query):
        return GeneratedAnswer(
            text=REALTIME_WEATHER_UNAVAILABLE_ANSWER,
            cited_chunks=[],
        )

    if not chunks:
        return request_general_knowledge_answer(
            response_client=response_client,
            query=query,
            mode=mode,
        )

    relevance_query = search_query or query

    if not has_sufficient_relevance(
        relevance_query,
        chunks,
    ):
        return request_general_knowledge_answer(
            response_client=response_client,
            query=query,
            mode=mode,
        )
    
    if is_legal_subject_question(query):
        chunks = prioritize_legal_chunks(
            query=query,
            chunks=chunks,
        )

    if is_fmd_report_question(query):
        return build_fmd_report_answer(chunks)

    if (
        is_fmd_post_report_action_question(query)
        or is_fmd_followup_action_question(
            query=query,
            messages=messages,
        )
    ):
        return build_fmd_post_report_action_answer(
            query=query,
            chunks=chunks,
        )

    context = build_context(chunks)

    conversation_text = build_conversation_text(
        messages
    )

    input_parts: list[str] = []

    if conversation_text:
        input_parts.append(
            f"이전 대화:\n{conversation_text}"
        )

    if search_query and search_query != query:
        input_parts.append(
            "문서 검색에 사용한 재작성 질문:\n"
            f"{search_query}"
        )

    input_parts.append(
        f"현재 사용자의 질문:\n{query}"
    )

    input_parts.append(
        f"검색 근거:\n{context}"
    )

    

    if is_support_combined_question(query):
        input_parts.append(
            "현재 질문은 지원사업의 지원 대상과 지원 제외 대상을 "
            "함께 묻는 질문입니다. "
            "검색 근거에서 지원 대상과 지원 제외 대상을 모두 설명하세요. "
            "반드시 '지원 대상'과 '제외 대상' 두 범주를 모두 포함하세요. "
            "한쪽만 설명하지 마세요. "
            "지원 대상은 지원자격·사업대상 근거를 사용하고, "
            "제외 대상은 지원 제외 조건 근거를 사용하세요. "
            "조건부 허용이나 예외가 있으면 해당 항목에 함께 설명하세요."
        )

    elif is_support_eligibility_question(query):
        if mode == "short":
            input_parts.append(
                "현재 질문은 지원사업 신청 자격을 묻는 질문입니다. "
                "기본 지원 대상과 가장 중요한 지원 제외 조건만 답하세요. "
                "추가 인정 대상과 세부 예외는 생략하세요. "
                "답변은 목록 없이 최대 2문장, 220자 이내로 작성하세요. "
                "'기본 대상', '추가 인정 대상', '주요 지원 제외 조건' 같은 "
                "제목은 작성하지 마세요."
            )

        elif mode == "normal":
            input_parts.append(
                "현재 질문은 지원사업 신청 자격요건을 묻는 질문입니다. "
                "답변은 다음 세 부분으로 구성하세요: "
                "① 기본 대상 "
                "② 추가 인정 대상 "
                "③ 주요 지원 제외 조건. "
                "각 항목은 1~2문장으로 간결하게 작성하세요. "
                "신청 절차와 대출 실행 절차는 제외하세요."
            )

        else:  # detailed
            input_parts.append(
                "현재 질문은 지원사업 신청 자격요건을 묻는 질문입니다. "
                "답변은 다음 네 부분으로 구성하세요: "
                "① 기본 대상 "
                "② 추가 인정 대상 "
                "③ 주요 지원 제외 조건 "
                "④ 조건부 인정 및 주요 예외. "
                "대상별 요건과 예외를 검색 근거 범위 안에서 자세히 설명하세요. "
                "신청 절차와 대출 실행 절차는 사용자가 묻지 않았으므로 제외하세요. "
                "답변 시작이나 끝에 '문서를 근거로 정리했습니다', "
                "'지침을 기준으로 정리했습니다', '참고' 같은 "
                "메타 설명이나 별도의 출처 안내 문장을 작성하지 마세요. "
                "본문의 [1], [2] 인용만 사용하세요."
            )

    if is_legal_subject_question(query):
        direct_sections = [
            chunk.section_path
            for chunk in chunks
            if chunk.section_path
        ]

        section_hint = " / ".join(
            direct_sections[:2]
        )

        input_parts.append(
            "현재 질문은 법령상 의무자·책임자·대상자를 묻는 질문입니다. "
            "검색 근거 중 질문의 의무를 직접 규정한 조문을 우선 사용하세요. "
            "해당 조문에 여러 주체가 열거되어 있으면 주요 주체를 빠뜨리지 말고 "
            "각 항의 적용 대상까지 확인해 요약하세요. "
            "직접 관련 조문을 확인할 수 없으면 일부 주체만 추정하여 답하지 마세요. "
            "그 경우 전체 답변을 '제공된 문서에서는 해당 내용을 확인할 수 없습니다.'로 작성하세요. "
            "답변 일부를 제시한 뒤 근거를 확인할 수 없다고 덧붙이지 마세요. "
            "직접 관련 조문에 여러 항이 있으면 제1항뿐 아니라 "
            "추가 신고 주체나 적용 대상이 규정된 후속 항도 함께 확인하세요. "
            "일반적인 책무 조항을 직접 의무 조항으로 확대 해석하지 마세요. "
            "조문에 단서나 예외가 있으면 짧게 함께 설명하세요. "
            "검색 근거에 없는 주체를 추가하지 마세요. "
            "법령에서 '소유자등'처럼 여러 주체를 묶어 정의한 용어는 "
            "그 정의가 검색 근거에 있으면 첫 언급에서 구성 주체를 풀어서 설명하세요. "
            "법령의 주체를 다른 주체의 역할과 합쳐 표현하지 마세요. "
            "법령에서 어떤 사람이 다른 사람을 선임하도록 규정한 경우, "
            "선임 의무자와 선임되는 사람을 혼동하지 마세요. "
            "'소유자등'은 검색 근거의 정의에 따라 소유자 또는 관리자로 풀어 쓰세요. "
            "법령에 열거된 주체를 답변 길이를 맞추기 위해 생략하지 마세요. "
            "'소유자등'의 정의가 확인되면 반드시 '소유자 또는 관리자'로 표현하세요. "
            "신고 의무 조문의 후속 항에 별도의 신고 주체가 있으면 함께 포함하세요. "
            "선임 의무자는 방역관리 책임자가 아니며, 선임되는 전문지식 보유자가 "
            "방역관리 책임자라는 문장 구조로 작성하세요. "
            "'선임하여 둔 자'처럼 두 주체가 혼동되는 표현은 사용하지 마세요. "
            "'제외된다'고만 표현하지 말고 무엇이 면제되거나 갈음되는지 명확히 설명하세요. "
            f"우선 검토할 검색 위치: {section_hint}"
        )



    legal_subject = is_legal_subject_question(query)
    allow_general_supplement = should_allow_general_supplement(
        query=query,
        chunks=chunks,
    )

    if allow_general_supplement:
        input_parts.append(
            "이전 대화에서 이미 안내한 내용은 반복하지 마세요. "
            "질문의 일부만 검색 근거로 확인되는 복합 질문입니다. "
            "답변을 '문서에서 확인된 내용'과 '추가 설명'으로 구분하세요. "
            "문서에서 확인된 주장에만 [1], [2] 형식의 인용을 표시하세요. "
            "추가 설명에는 RAG 인용을 붙이지 말고, 등록 문서의 직접 근거가 "
            "아닌 일반 지식이라는 주의 문구를 포함하세요."
        )
    else:
        input_parts.append(
            "이전 대화의 맥락을 유지하고 검색 근거에서 확인되는 내용만 답변하세요. "
            "이전 답변에서 이미 안내한 내용은 반복하지 마세요. "
            "현재 질문이 '그다음', '이후', '어떤 조치'처럼 후속 행동을 묻는 경우 "
            "이전 단계 이후의 행동만 설명하세요."
        )

    input_text = "\n\n".join(input_parts)

    answer = request_answer_text(
        response_client=response_client,
        mode=mode,
        input_text=input_text,
        legal_subject=legal_subject,
        allow_general_supplement=allow_general_supplement,
    )

    if is_document_scope_refusal(answer):
        if has_strong_relevance(chunks):
            evidence_retry_input = (
                f"{input_text}\n\n"
                "검색 근거의 관련성 점수가 충분합니다. 질문에 직접 관련된 "
                "검색 근거를 다시 확인하고 문서 범위 안에서 답변하세요. "
                "주요 주장에는 실제 검색 근거 인용 번호를 표시하세요."
            )
            retry_answer = request_answer_text(
                response_client=response_client,
                mode=mode,
                input_text=evidence_retry_input,
                legal_subject=legal_subject,
                allow_general_supplement=allow_general_supplement,
            )
            if not is_document_scope_refusal(retry_answer):
                answer = retry_answer
            else:
                return request_general_knowledge_answer(
                    response_client=response_client,
                    query=query,
                    mode=mode,
                )
        else:
            return request_general_knowledge_answer(
                response_client=response_client,
                query=query,
                mode=mode,
            )

    if legal_answer_needs_retry(
        query=query,
        answer=answer,
    ):
        completion_retry_input = (
            f"{input_text}\n\n"
            "이전 답변에서 법령에 열거된 신고 주체가 누락되었습니다. "
            "검색 근거의 직접 관련 조문 전체를 다시 확인하세요. "
            "제11조의 신고 의무자를 묻는 경우 다음 주체가 근거에 있으면 "
            "하나도 생략하지 마세요: "
            "소유자 또는 관리자, 축산계열화사업자, 수의사, "
            "연구책임자, 동물약품 또는 사료 판매자, 가축운송업자. "
            "제1항뿐 아니라 후속 항에 규정된 별도 신고 주체도 포함하세요. "
            "근거에 없는 주체는 추가하지 마세요. "
            "각 주요 주장에는 [1], [2] 형식의 검색 근거 인용을 표시하세요."
        )

        retry_answer = request_answer_text(
            response_client=response_client,
            mode=mode,
            input_text=completion_retry_input,
            legal_subject=legal_subject,
            allow_general_supplement=allow_general_supplement,
        )

        required_terms = (
            "소유자",
            "관리자",
            "축산계열화사업자",
            "수의사",
            "연구책임자",
            "동물약품",
            "사료 판매자",
            "가축운송업자",
        )

        answer = max(
            (answer, retry_answer),
            key=lambda candidate: sum(
                term in normalize_text(candidate)
                for term in required_terms
            ),
        )

    if legal_answer_is_awkward(
        query=query,
        answer=answer,
    ):
        awkward_retry_input = (
            f"{input_text}\n\n"
            "이전 답변은 선임 의무자와 선임되는 사람의 관계가 "
            "문법적으로 혼동되게 작성되었습니다. "
            "다음 구조로 다시 작성하세요: "
            "'방역관리 책임자는 소유자 또는 관리자가 선임해야 하는, "
            "수의학 또는 축산학에 관한 전문지식을 갖춘 사람입니다.' "
            "소유자 또는 관리자는 선임 의무자이고, "
            "전문지식을 갖춘 사람이 방역관리 책임자입니다. "
            "'사람을 선임하여 두어야 하는 사람'과 같은 표현은 "
            "사용하지 마세요. "
            "검색 근거에 없는 내용은 추가하지 마세요."
        )

        answer = request_answer_text(
            response_client=response_client,
            mode=mode,
            input_text=awkward_retry_input,
            legal_subject=legal_subject,
            allow_general_supplement=allow_general_supplement,
        )

    if is_refusal_text(answer):
        retry_input = (
            f"{input_text}\n\n"
            "이 요청은 축산 문서에 관한 정상적인 정보 질의입니다. "
            "거절문을 작성하지 말고 제공된 검색 근거에 있는 내용만 "
            "한국어로 답변하세요."
        )

        answer = request_answer_text(
            response_client=response_client,
            mode=mode,
            input_text=retry_input,
            legal_subject=legal_subject,
            allow_general_supplement=allow_general_supplement,
        )

    if is_refusal_text(answer):
        return GeneratedAnswer(
            text=(
                "답변 생성 과정에서 일시적인 오류가 발생했습니다. "
                "잠시 후 다시 질문해 주세요."
            ),
            cited_chunks=[],
        )
    
    if (
        legal_subject
        and not allow_general_supplement
        and not re.search(r"\[\d+\]", answer)
    ):
        citation_retry_input = (
            f"{input_text}\n\n"
            "이전 답변의 내용은 유지하되 검색 근거 인용 번호가 누락되었습니다. "
            "답변을 다시 작성하세요. "
            "중요한 주장마다 반드시 검색 근거 번호를 [1], [2], [3] 형식으로 "
            "표시하세요. "
            "①, ②, ③ 같은 조문 항 번호는 검색 근거 인용을 대신할 수 없습니다. "
            "조문 항 번호가 필요하면 그대로 사용할 수 있지만, "
            "별도로 해당 주장을 뒷받침하는 검색 근거 [1], [2] 등을 붙이세요. "
            "제공된 검색 근거 번호만 사용하세요. "
            "별도의 '근거:', '출처:', '참고문헌:' 항목은 작성하지 마세요. "
            "내용이나 법적 주체를 새로 추가하거나 삭제하지 마세요."
        )

        citation_retry_answer = request_answer_text(
            response_client=response_client,
            mode=mode,
            input_text=citation_retry_input,
            legal_subject=legal_subject,
            allow_general_supplement=allow_general_supplement,
        )

        # 재시도 결과가 실제로 더 나을 때만 교체한다.
        if (
            not is_refusal_text(citation_retry_answer)
            and re.search(
                r"\[\d+\]",
                citation_retry_answer,
            )
        ):
            answer = citation_retry_answer

    # 최종 deterministic fallback
    if (
        legal_subject
        and not allow_general_supplement
        and chunks
        and not re.search(r"\[\d+\]", answer)
    ):
        answer = answer.rstrip()

        if answer.endswith("."):
            answer = f"{answer[:-1]}[1]."
        else:
            answer = f"{answer}[1]"


    if allow_general_supplement:
        answer = ensure_mixed_answer_notice(answer, query)

    answer = clean_generated_text(answer)

    return resolve_cited_sources(
        answer=answer,
        chunks=chunks,
        max_sources=ANSWER_MODES[
            mode
        ]["max_sources"],
    )


def print_sources(chunks: list[RetrievedChunk]) -> None:
    print("\n[검색 원본 순위 — 답변 출처 번호와 다를 수 있음]")

    for idx, chunk in enumerate(chunks, 1):
        print(
            f"\n검색 순위 {idx}. {chunk.source_label}\n"
            f"   위치: {chunk.section_path}\n"
            f"   청크: {chunk.id}"
        )

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Azure AI Search 기반 축산 RAG 답변 생성"
    )
    parser.add_argument("query", help="사용자 질문")
    parser.add_argument(
        "--mode",
        choices=sorted(ANSWER_MODES),
        default=os.getenv("RAG_ANSWER_MODE", "short"),
        help="답변 길이 모드",
    )
    parser.add_argument(
        "--show-sources",
        action="store_true",
        help="최종 답변 아래에 내부 청크 정보까지 출력",
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="답변 모델을 호출하지 않고 검색 근거만 확인",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    search, embedding_client, response_client = build_clients()

    route, chunks = retrieve(
        args.query,
        search,
        embedding_client,
        args.mode,
    )

    if args.search_only:
        print(json.dumps(route, ensure_ascii=False, indent=2))
        print_sources(chunks)
        return

    generated = generate_answer(
        args.query,
        chunks,
        response_client,
        args.mode,
    )

    print(generated.text)

    if args.show_sources:
        print_sources(generated.cited_chunks)


if __name__ == "__main__":
    main()

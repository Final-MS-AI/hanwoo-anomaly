from __future__ import annotations

import json
from pathlib import Path

from rag.rag_answer import build_clients, retrieve


EVAL_PATH = Path("evaluation_cases.json")
RESULT_PATH = Path("search_evaluation_result.json")


def normalize(text: str) -> str:
    return "".join((text or "").lower().split())

KEYWORD_ALTERNATIVES = {
    "대기": [
        "대기",
        "기다려",
        "도착할 때까지",
        "떠나지 말고",
    ],
    "예외": [
        "예외",
        "제외",
        "다만",
        "그러하지 아니",
    ],
    "지원 제외": [
        "지원 제외",
        "지원대상에서 제외",
        "제외 대상",
        "무허가 축사",
    ],
    "제외 조건": [
        "제외 조건",
        "지원대상에서 제외",
        "지원 제외",
        "무허가 축사",
    ],
    "지원 대상": [
        "지원 대상",
        "지원대상",
        "사업 대상",
        "사업대상",
        "지원자격",
    ],
    "제외": [
        "제외",
        "제외 대상",
        "지원대상에서 제외",
        "무허가 축사",
        "지원 불가",
    ],
    "의무": [
        "의무",
        "신고하여야",
        "신고해야",
        "하여야 한다",
    ],
}


def keyword_matches(text: str, keyword: str) -> bool:
    normalized_text = normalize(text)

    alternatives = KEYWORD_ALTERNATIVES.get(
        keyword,
        [keyword],
    )

    return any(
        normalize(candidate) in normalized_text
        for candidate in alternatives
    )


def find_rank(
    chunks,
    keywords: list[str],
) -> int | None:
    """
    Top-K까지의 검색 결과를 누적해서
    expected_keywords가 모두 충족되는 최초 K를 반환한다.

    예:
    #1 청크에 '지원 대상'
    #2 청크에 '제외'
    -> rank=2
    """

    accumulated_parts = []

    for index, chunk in enumerate(chunks, start=1):
        accumulated_parts.extend(
            [
                chunk.document_title or "",
                chunk.section_path or "",
                chunk.content or "",
            ]
        )

        accumulated_text = " ".join(
            accumulated_parts
        )

        if all(
            keyword_matches(
                accumulated_text,
                keyword,
            )
            for keyword in keywords
        ):
            return index

    return None

def main():
    if not EVAL_PATH.exists():
        raise FileNotFoundError(
            f"평가 파일을 찾을 수 없습니다: {EVAL_PATH.resolve()}"
        )

    cases = json.loads(
        EVAL_PATH.read_text(encoding="utf-8")
    )

    search_client, embedding_client, _ = build_clients()

    total = len(cases)

    top1 = 0
    top3 = 0
    top5 = 0
    misses = []

    results = []

    print("=" * 100)
    print("RAG SEARCH EVALUATION")
    print("=" * 100)

    for case in cases:
        case_id = case["id"]
        question = case["question"]
        expected_keywords = case.get(
            "expected_keywords",
            [],
        )

        try:
            route, chunks = retrieve(
                query=question,
                search=search_client,
                aoai=embedding_client,
                mode="normal",
            )

            rank = find_rank(
                chunks,
                expected_keywords,
            )

            if rank == 1:
                top1 += 1

            if rank is not None and rank <= 3:
                top3 += 1

            if rank is not None and rank <= 5:
                top5 += 1

            status = (
                f"rank={rank}"
                if rank is not None
                else "MISS"
            )

            print(
                f"{case_id:>8} | "
                f"{status:<8} | "
                f"route={route.get('route'):<26} | "
                f"keywords={expected_keywords}"
            )

            result_item = {
                "id": case_id,
                "question": question,
                "expected_keywords": expected_keywords,
                "route": route.get("route"),
                "rank": rank,
                "top_chunks": [
                    {
                        "rank": i,
                        "id": chunk.id,
                        "document_title": chunk.document_title,
                        "document_type": chunk.document_type,
                        "page": chunk.page_label,
                        "section_path": chunk.section_path,
                        "content_preview": (
                            chunk.content[:250]
                            .replace("\n", " ")
                        ),
                    }
                    for i, chunk in enumerate(
                        chunks[:5],
                        start=1,
                    )
                ],
            }

            results.append(result_item)

            if rank is None:
                misses.append(result_item)

        except Exception as exc:
            print(
                f"{case_id:>8} | ERROR    | "
                f"{type(exc).__name__}: {exc}"
            )

            item = {
                "id": case_id,
                "question": question,
                "expected_keywords": expected_keywords,
                "route": None,
                "rank": None,
                "error": f"{type(exc).__name__}: {exc}",
                "top_chunks": [],
            }

            results.append(item)
            misses.append(item)

    def ratio(value: int) -> float:
        return value / total if total else 0.0

    print()
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)

    print(f"total : {total}")
    print(
        f"top1  : {top1}/{total} "
        f"({ratio(top1) * 100:.2f}%)"
    )
    print(
        f"top3  : {top3}/{total} "
        f"({ratio(top3) * 100:.2f}%)"
    )
    print(
        f"top5  : {top5}/{total} "
        f"({ratio(top5) * 100:.2f}%)"
    )
    print(f"miss  : {len(misses)}")

    if misses:
        print()
        print("=" * 100)
        print("MISS DETAILS")
        print("=" * 100)

        for item in misses:
            print()
            print(
                f"[{item['id']}] "
                f"{item['question']}"
            )

            if "error" in item:
                print(
                    "ERROR:",
                    item["error"],
                )
                continue

            print(
                "expected_keywords:",
                item["expected_keywords"],
            )

            for chunk in item["top_chunks"]:
                print(
                    f"  #{chunk['rank']} "
                    f"{chunk['document_title']} | "
                    f"{chunk['page']} | "
                    f"{chunk['section_path']}"
                )
                print(
                    "     ",
                    chunk["content_preview"],
                )

    output = {
        "total": total,
        "top1": top1,
        "top3": top3,
        "top5": top5,
        "top1_accuracy": round(
            ratio(top1),
            4,
        ),
        "top3_accuracy": round(
            ratio(top3),
            4,
        ),
        "top5_accuracy": round(
            ratio(top5),
            4,
        ),
        "miss": len(misses),
        "results": results,
    }

    RESULT_PATH.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 100)
    print(
        "결과 저장:",
        RESULT_PATH.resolve(),
    )


if __name__ == "__main__":
    main()

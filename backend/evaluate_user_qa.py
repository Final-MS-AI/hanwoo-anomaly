from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests


CASES_PATH = Path("qa_user_cases.json")
RESULT_PATH = Path("qa_user_qa_result.json")

API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000/rag/chat")


BAD_PATTERNS = (
    "직접적 답변:",
    "직접적인 답변:",
    "핵심 근거:",
    "핵심 근거 및 예외사항:",
    "검색 근거:",
    "참고문헌:",
    "출처:",
    "\\~",
)


def check_answer(answer: str, sources: list) -> dict:
    issues = []

    if not answer.strip():
        issues.append("empty_answer")

    for pattern in BAD_PATTERNS:
        if pattern in answer:
            issues.append(f"bad_pattern:{pattern}")

    citation_numbers = [
        int(x)
        for x in re.findall(r"\[(\d+)\]", answer)
    ]

    if citation_numbers:
        max_citation = max(citation_numbers)

        if max_citation > len(sources):
            issues.append(
                f"invalid_citation:max={max_citation},sources={len(sources)}"
            )

    if (
        answer.strip()
        == "제공된 문서에서는 해당 내용을 확인할 수 없습니다."
        and sources
    ):
        issues.append("refusal_with_sources")

    return {
        "issues": issues,
        "citation_numbers": citation_numbers,
    }


def main():
    if not CASES_PATH.exists():
        print(
            f"평가 케이스 파일이 없습니다: {CASES_PATH.resolve()}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    cases = json.loads(
        CASES_PATH.read_text(encoding="utf-8")
    )

    results = []

    total = len(cases)
    http_ok = 0
    clean = 0
    refused = 0

    print("=" * 110)
    print("RAG USER QA EVALUATION")
    print("=" * 110)

    for case in cases:
        case_id = case["id"]
        question = case["question"]
        mode = case.get("mode", "normal")

        payload = {
            "question": question,
            "mode": mode,
        }

        try:
            response = requests.post(
                API_URL,
                json=payload,
                timeout=120,
            )

            status_code = response.status_code

            if status_code != 200:
                print(
                    f"{case_id} | HTTP {status_code} | "
                    f"{question}"
                )

                results.append(
                    {
                        "id": case_id,
                        "question": question,
                        "mode": mode,
                        "status_code": status_code,
                        "error": response.text[:1000],
                    }
                )

                continue

            http_ok += 1

            data = response.json()

            answer = str(
                data.get("answer", "")
            ).strip()

            sources = (
                data.get("sources", [])
                or []
            )

            validation = check_answer(
                answer=answer,
                sources=sources,
            )

            issues = validation["issues"]

            is_refusal = (
                answer
                == "제공된 문서에서는 해당 내용을 확인할 수 없습니다."
            )

            if is_refusal:
                refused += 1

            if not issues:
                clean += 1

            status = (
                "PASS"
                if not issues
                else "WARN"
            )

            print(
                f"{case_id} | "
                f"{status:<4} | "
                f"mode={mode:<8} | "
                f"len={len(answer):>4} | "
                f"sources={len(sources):>2} | "
                f"{question}"
            )

            if issues:
                print(
                    " " * 9
                    + "issues="
                    + ", ".join(issues)
                )

            results.append(
                {
                    "id": case_id,
                    "question": question,
                    "mode": mode,
                    "status_code": status_code,
                    "answer": answer,
                    "answer_length": len(answer),
                    "sources_count": len(sources),
                    "sources": sources,
                    "citation_numbers": validation[
                        "citation_numbers"
                    ],
                    "issues": issues,
                    "refusal": is_refusal,
                }
            )

        except Exception as exc:
            print(
                f"{case_id} | ERROR | "
                f"{type(exc).__name__}: {exc}"
            )

            results.append(
                {
                    "id": case_id,
                    "question": question,
                    "mode": mode,
                    "status_code": None,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            )

    print()
    print("=" * 110)
    print("SUMMARY")
    print("=" * 110)
    print(f"total      : {total}")
    print(f"http_ok    : {http_ok}/{total}")
    print(f"clean      : {clean}/{total}")
    print(f"refused    : {refused}")
    print(f"http_error : {total - http_ok}")

    print()
    print("=" * 110)
    print("ANSWER PREVIEW")
    print("=" * 110)

    for item in results:
        if "answer" not in item:
            continue

        print()
        print(
            f"[{item['id']}] "
            f"{item['question']}"
        )
        print(
            "-" * 100
        )
        print(
            item["answer"][:1200]
        )
        print()
        print(
            f"sources={item['sources_count']} "
            f"issues={item['issues']}"
        )

    RESULT_PATH.write_text(
        json.dumps(
            {
                "total": total,
                "http_ok": http_ok,
                "clean": clean,
                "refused": refused,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 110)
    print(
        "결과 저장:",
        RESULT_PATH.resolve(),
    )


if __name__ == "__main__":
    main()

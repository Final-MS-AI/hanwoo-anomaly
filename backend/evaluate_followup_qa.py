import json
import os
from pathlib import Path

import requests

API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000/rag/chat")
ROOT = Path(__file__).resolve().parent

CASES_PATH = ROOT / "qa_followup_cases.json"
RESULT_PATH = ROOT / "qa_followup_qa_result.json"


def check_answer(answer: str, sources: list[dict]) -> list[str]:
    issues = []

    if not answer.strip():
        issues.append("empty_answer")

    bad_patterns = (
        "직접적인 답변:",
        "직접적 답변:",
        "핵심 근거 및 예외사항:",
        "변:",
    )

    for pattern in bad_patterns:
        if pattern in answer:
            issues.append(f"bad_text:{pattern}")

    # 범위를 벗어난 인용 번호 확인
    import re

    citation_numbers = [
        int(x)
        for x in re.findall(r"\[(\d+)\]", answer)
    ]

    if citation_numbers:
        max_citation = max(citation_numbers)

        if max_citation > len(sources):
            issues.append(
                f"invalid_citation:{max_citation}>{len(sources)}"
            )

    return issues


def main():
    with CASES_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:
        cases = json.load(f)

    print("=" * 110)
    print("RAG FOLLOW-UP QA EVALUATION")
    print("=" * 110)

    results = []

    http_ok = 0
    clean = 0
    http_error = 0

    for case in cases:
        case_id = case["id"]
        question = case["question"]
        mode = case.get("mode", "normal")
        messages = case.get("messages", [])

        payload = {
            "question": question,
            "mode": mode,
            "messages": messages,
        }

        try:
            response = requests.post(
                API_URL,
                json=payload,
                timeout=120,
            )

            if response.status_code != 200:
                print(
                    f"{case_id} | HTTP {response.status_code} | "
                    f"{question}"
                )

                results.append(
                    {
                        **case,
                        "status_code": response.status_code,
                        "error": response.text,
                    }
                )

                http_error += 1
                continue

            http_ok += 1

            data = response.json()

            answer = data.get("answer", "")
            sources = data.get("sources", [])

            issues = check_answer(
                answer=answer,
                sources=sources,
            )

            if not issues:
                clean += 1
                status = "PASS"
            else:
                status = "CHECK"

            print(
                f"{case_id} | {status:5s} | "
                f"mode={mode:8s} | "
                f"len={len(answer):4d} | "
                f"sources={len(sources):2d} | "
                f"{question}"
            )

            results.append(
                {
                    **case,
                    "status_code": 200,
                    "answer": answer,
                    "sources": sources,
                    "issues": issues,
                }
            )

        except Exception as exc:
            print(
                f"{case_id} | ERROR | "
                f"{type(exc).__name__}: {exc}"
            )

            results.append(
                {
                    **case,
                    "status_code": None,
                    "error": str(exc),
                }
            )

            http_error += 1

    print()
    print("=" * 110)
    print("SUMMARY")
    print("=" * 110)
    print(f"total      : {len(cases)}")
    print(f"http_ok    : {http_ok}/{len(cases)}")
    print(f"clean      : {clean}/{len(cases)}")
    print(f"http_error : {http_error}")

    print()
    print("=" * 110)
    print("ANSWER PREVIEW")
    print("=" * 110)

    for item in results:
        if item.get("status_code") != 200:
            continue

        print()
        print(
            f"[{item['id']}] "
            f"{item['question']}"
        )
        print("-" * 100)
        print(item["answer"])
        print()
        print(
            f"sources={len(item['sources'])} "
            f"issues={item['issues']}"
        )

    output = {
        "summary": {
            "total": len(cases),
            "http_ok": http_ok,
            "clean": clean,
            "http_error": http_error,
        },
        "results": results,
    }

    with RESULT_PATH.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("=" * 110)
    print(f"결과 저장: {RESULT_PATH}")


if __name__ == "__main__":
    main()

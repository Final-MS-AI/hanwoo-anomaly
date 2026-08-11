from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from rag.query_router import route_query


PATH = Path("router_negative_cases.json")


def main():
    cases = json.loads(
        PATH.read_text(encoding="utf-8")
    )

    total = len(cases)
    correct = 0
    mismatches = []
    actual_counter = Counter()

    print("=" * 90)
    print("RAG ROUTER NEGATIVE / OVERROUTING EVALUATION")
    print("=" * 90)

    for case in cases:
        result = route_query(case["question"])

        expected = case["expected_route"]
        actual = result["route"]

        actual_counter[actual] += 1

        if actual == expected:
            correct += 1
            status = "PASS"
        else:
            status = "FAIL"
            mismatches.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "expected": expected,
                    "actual": actual,
                    "filter": result.get("filter"),
                    "top_k": result.get("top_k"),
                }
            )

        print(
            f"{case['id']:>8} | "
            f"{status:<4} | "
            f"expected={expected:<26} | "
            f"actual={actual}"
        )

    accuracy = correct / total if total else 0.0

    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"total    : {total}")
    print(f"correct  : {correct}")
    print(f"mismatch : {total - correct}")
    print(f"accuracy : {accuracy:.4f} ({accuracy * 100:.2f}%)")

    print()
    print("=" * 90)
    print("ACTUAL ROUTE DISTRIBUTION")
    print("=" * 90)

    for route, count in sorted(actual_counter.items()):
        print(f"{route:<28} {count}")

    if mismatches:
        print()
        print("=" * 90)
        print("MISMATCH DETAILS")
        print("=" * 90)

        for item in mismatches:
            print()
            print(
                f"[{item['id']}] "
                f"expected={item['expected']} "
                f"actual={item['actual']}"
            )
            print(f"Q: {item['question']}")
            print(f"top_k: {item['top_k']}")
            print(f"filter: {item['filter']}")

    output = {
        "total": total,
        "correct": correct,
        "mismatch": total - correct,
        "accuracy": round(accuracy, 4),
        "mismatches": mismatches,
    }

    Path("router_negative_result.json").write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 90)
    print("결과 저장: router_negative_result.json")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from rag.query_router import route_query


EVAL_PATH = Path("evaluation_cases.json")


def main():
    if not EVAL_PATH.exists():
        raise FileNotFoundError(
            f"평가 파일을 찾을 수 없습니다: {EVAL_PATH.resolve()}"
        )

    cases = json.loads(
        EVAL_PATH.read_text(encoding="utf-8")
    )

    total = len(cases)
    correct = 0

    expected_counter = Counter()
    actual_counter = Counter()

    per_route = defaultdict(
        lambda: {
            "total": 0,
            "correct": 0,
        }
    )

    mismatches = []

    print("=" * 90)
    print("RAG ROUTER EVALUATION")
    print("=" * 90)

    for case in cases:
        case_id = case["id"]
        question = case["question"]
        expected = case["expected_route"]

        result = route_query(question)
        actual = result["route"]

        expected_counter[expected] += 1
        actual_counter[actual] += 1

        per_route[expected]["total"] += 1

        is_correct = actual == expected

        if is_correct:
            correct += 1
            per_route[expected]["correct"] += 1
            status = "PASS"
        else:
            status = "FAIL"

            mismatches.append(
                {
                    "id": case_id,
                    "question": question,
                    "expected": expected,
                    "actual": actual,
                    "filter": result.get("filter"),
                    "top_k": result.get("top_k"),
                }
            )

        print(
            f"{case_id:>8} | "
            f"{status:<4} | "
            f"expected={expected:<26} | "
            f"actual={actual}"
        )

    accuracy = (
        correct / total
        if total
        else 0.0
    )

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
    print("PER ROUTE")
    print("=" * 90)

    for route_name in sorted(per_route):
        route_total = per_route[route_name]["total"]
        route_correct = per_route[route_name]["correct"]

        route_accuracy = (
            route_correct / route_total
            if route_total
            else 0.0
        )

        print(
            f"{route_name:<28} "
            f"{route_correct:>2}/{route_total:<2} "
            f"{route_accuracy * 100:>6.2f}%"
        )

    print()
    print("=" * 90)
    print("EXPECTED ROUTE DISTRIBUTION")
    print("=" * 90)

    for route, count in sorted(expected_counter.items()):
        print(f"{route:<28} {count}")

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
        "per_route": {
            route: {
                "total": values["total"],
                "correct": values["correct"],
                "accuracy": round(
                    values["correct"] / values["total"],
                    4,
                )
                if values["total"]
                else 0.0,
            }
            for route, values in sorted(per_route.items())
        },
        "mismatches": mismatches,
    }

    output_path = Path("router_evaluation_result.json")

    output_path.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 90)
    print(
        "결과 저장:",
        output_path.resolve(),
    )


if __name__ == "__main__":
    main()

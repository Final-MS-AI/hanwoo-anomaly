from __future__ import annotations

import json
import sys
from pathlib import Path


def percentage(value: float | int | None) -> str:
    if value is None:
        return "N/A"

    return f"{float(value) * 100:.2f}%"


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "사용법: python show_metrics.py "
            "<evaluation_results.json 경로>"
        )
        raise SystemExit(1)

    result_path = Path(sys.argv[1]).expanduser().resolve()

    if not result_path.exists():
        raise FileNotFoundError(
            f"평가 결과 파일을 찾을 수 없습니다: {result_path}"
        )

    results = json.loads(
        result_path.read_text(encoding="utf-8")
    )

    total = results.get("total", 0)
    top1 = results.get("top1_accuracy")
    top3 = results.get("top3_accuracy")
    top5 = results.get("top5_accuracy")
    router = results.get("router_accuracy")

    print("=" * 50)
    print("RAG 검색 성능 평가 결과")
    print("=" * 50)
    print(f"평가 질문 수       : {total}")
    print(f"Top-1 Accuracy    : {percentage(top1)}")
    print(f"Top-3 Accuracy    : {percentage(top3)}")
    print(f"Top-5 Accuracy    : {percentage(top5)}")
    print(f"Router Accuracy   : {percentage(router)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
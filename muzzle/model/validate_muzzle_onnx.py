from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np

from muzzle_encoder_onnx import MuzzleEncoderONNX


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
}


def collect_images(
    data_dir: Path,
) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = defaultdict(list)

    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        stem = path.stem

        if "__" in stem:
            cattle_id = stem.split("__", 1)[0]
        else:
            cattle_id = path.parent.name

        grouped[cattle_id].append(path)

    return {
        cattle_id: sorted(paths)
        for cattle_id, paths in grouped.items()
        if len(paths) >= 4
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "CFF 비문 Crop 데이터로 ONNX 인코더의 "
            "등록·식별 성능을 검증합니다."
        )
    )

    parser.add_argument(
        "--data",
        default="results/cff_crops",
        help="비문 Crop 이미지 폴더",
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=0.40,
        help="개체 확정 임계값",
    )

    parser.add_argument(
        "--enroll-count",
        type=int,
        default=3,
        help="개체별 등록에 사용할 이미지 수",
    )

    args = parser.parse_args()

    data_dir = Path(args.data)

    if not data_dir.is_dir():
        raise FileNotFoundError(
            f"데이터 폴더가 없습니다: {data_dir}"
        )

    grouped = collect_images(data_dir)

    if not grouped:
        raise RuntimeError(
            "개체당 이미지가 4장 이상인 데이터를 찾지 못했습니다."
        )

    print("[데이터 확인]")
    print("데이터 폴더:", data_dir.resolve())
    print("개체 수:", len(grouped))
    print(
        "전체 이미지 수:",
        sum(len(paths) for paths in grouped.values()),
    )
    print("등록 이미지 수/개체:", args.enroll_count)
    print("운영 임계값:", args.threshold)

    encoder = MuzzleEncoderONNX(
        threshold=args.threshold
    )

    gallery: dict[str, np.ndarray] = {}
    probe_paths: list[Path] = []
    probe_truth: list[str] = []

    print("\n[등록 임베딩 생성]")

    for index, (cattle_id, paths) in enumerate(
        sorted(grouped.items()),
        start=1,
    ):
        if len(paths) <= args.enroll_count:
            continue

        enroll_paths = paths[:args.enroll_count]
        probe_candidates = paths[args.enroll_count:]

        gallery[cattle_id] = encoder.enroll(
            enroll_paths
        )

        probe_paths.extend(probe_candidates)
        probe_truth.extend(
            [cattle_id] * len(probe_candidates)
        )

        if index == 1 or index % 10 == 0:
            print(
                f"등록 진행: {index}/{len(grouped)}"
            )

    if not gallery:
        raise RuntimeError(
            "등록 Gallery를 만들지 못했습니다."
        )

    print("\n[조회 임베딩 생성]")
    probe_embeddings = encoder.embed(
        probe_paths
    )

    gallery_ids = list(gallery.keys())
    gallery_matrix = np.stack(
        [
            gallery[cattle_id]
            for cattle_id in gallery_ids
        ],
        axis=0,
    )

    similarities = (
        probe_embeddings
        @ gallery_matrix.T
    )

    best_indexes = similarities.argmax(axis=1)
    best_scores = similarities.max(axis=1)

    predicted_ids = np.array(
        [
            gallery_ids[index]
            for index in best_indexes
        ]
    )

    truth_ids = np.array(probe_truth)

    correct = predicted_ids == truth_ids
    assigned = best_scores >= args.threshold
    held = ~assigned
    misassigned = assigned & ~correct

    probe_count = len(probe_truth)

    top1 = float(correct.mean())
    misassign_rate = float(
        misassigned.sum() / probe_count
    )
    hold_rate = float(
        held.sum() / probe_count
    )

    assigned_count = int(assigned.sum())

    if assigned_count > 0:
        accuracy_within_coverage = float(
            correct[assigned].mean()
        )
    else:
        accuracy_within_coverage = 0.0

    print("\n" + "=" * 62)
    print("[ONNX 비문 식별 검증 결과]")
    print("등록 개체 수:", len(gallery))
    print("조회 이미지 수:", probe_count)
    print(f"Top-1 정확도: {top1:.4f}")
    print(
        f"오배정률 @{args.threshold:.2f}: "
        f"{misassign_rate:.4f}"
    )
    print(
        f"보류율 @{args.threshold:.2f}: "
        f"{hold_rate:.4f}"
    )
    print(
        "커버리지 내 정확도:",
        f"{accuracy_within_coverage:.4f}",
    )
    print(
        "확정 건수:",
        f"{assigned_count}/{probe_count}",
    )
    print("=" * 62)

    print("\n[기존 CFF 기준값]")
    print("Top-1: 0.8127")
    print("오배정률 @0.40: 0.1873")
    print("보류율 @0.40: 0.0000")

    top1_difference = abs(top1 - 0.8127)
    misassign_difference = abs(
        misassign_rate - 0.1873
    )
    hold_difference = abs(
        hold_rate - 0.0000
    )

    print("\n[기존 결과와 차이]")
    print(
        "Top-1 차이:",
        f"{top1_difference:.4f}",
    )
    print(
        "오배정률 차이:",
        f"{misassign_difference:.4f}",
    )
    print(
        "보류율 차이:",
        f"{hold_difference:.4f}",
    )

    reproducible = (
        top1_difference <= 0.03
        and misassign_difference <= 0.03
        and hold_difference <= 0.03
    )

    if reproducible:
        print(
            "\n판정: 기존 CFF 결과와 유사하게 재현됐습니다."
        )
    else:
        print(
            "\n판정: 기존 결과와 차이가 큽니다. "
            "전처리 또는 데이터 분할 방식을 확인해야 합니다."
        )

    error_indexes = np.where(
        misassigned
    )[0]

    if len(error_indexes) > 0:
        print("\n[오배정 예시 최대 10건]")

        for index in error_indexes[:10]:
            print(
                f"- 파일={probe_paths[index].name}, "
                f"정답={truth_ids[index]}, "
                f"예측={predicted_ids[index]}, "
                f"유사도={best_scores[index]:.4f}"
            )


if __name__ == "__main__":
    main()

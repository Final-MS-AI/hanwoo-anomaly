from __future__ import annotations

import json
import os
from dataclasses import is_dataclass, replace
from pathlib import Path
from typing import Any


def apply_policy_overrides(thresholds: dict[str, Any]) -> dict[str, Any]:
    """Merge the reviewed weekly policy file into runtime thresholds safely."""
    path = Path(
        os.getenv(
            "FEEDBACK_POLICY_PATH",
            Path(__file__).resolve().parent / "feedback_policy_overrides.json",
        )
    )
    if not path.is_file():
        return thresholds

    try:
        overrides = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return thresholds

    merged = dict(thresholds)
    for behavior, values in overrides.items():
        current = merged.get(behavior)
        if current is None or not isinstance(values, dict):
            continue
        caution = float(values.get("caution_ratio", 0))
        anomaly = float(values.get("anomaly_ratio", 0))
        if not (0.10 <= caution <= 0.80 and caution + 0.10 <= anomaly <= 0.90):
            continue
        if is_dataclass(current):
            merged[behavior] = replace(
                current,
                caution_ratio=caution,
                anomaly_ratio=anomaly,
            )
        elif isinstance(current, dict):
            merged[behavior] = {
                **current,
                "caution_ratio": caution,
                "anomaly_ratio": anomaly,
            }
    return merged

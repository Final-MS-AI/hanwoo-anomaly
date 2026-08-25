from __future__ import annotations

import collections
import math
import sys
from pathlib import Path
from typing import Any

import cv2


BEHAVIOR_PACKAGE_DIR = Path(
    "/home/azureuser/models/detection/cow-model/"
    "hanwoo_behavior_anomaly_share_20260811"
)

ANALYSIS_BEHAVIORS = {
    "lying",
    "standing",
    "walking",
}

EXCLUDED_BEHAVIORS = {
    "feeding",
}


def load_original_pipeline():
    package_path = str(BEHAVIOR_PACKAGE_DIR)

    if package_path not in sys.path:
        sys.path.insert(0, package_path)

    import cow_pipeline

    return cow_pipeline


def collect_track_behavior_durations(
    *,
    input_path: Path,
    detector_path: Path,
    behavior_model_path: Path,
    behavior_specialist_path: Path,
    verifier_path: Path | None = None,
    verifier_imgsz: int = 224,
    verifier_conf: float = 0.80,
    feeding_threshold: float = 0.85,
    walking_threshold: float = 0.55,
    behavior_imgsz: int = 224,
    tracker: str = "bytetrack.yaml",
    conf: float = 0.05,
    iou: float = 0.45,
    imgsz: int = 960,
    classes: list[int] | None = None,
    window_seconds: float = 1.0,
    min_history: int = 5,
    move_threshold: float = 0.12,
    lying_ratio: float = 1.75,
) -> dict[str, Any]:
    from ultralytics import YOLO

    cow_pipeline = load_original_pipeline()

    TrackState = cow_pipeline.TrackState
    classify_motion = cow_pipeline.classify_motion
    resolve_behavior_label = (
        cow_pipeline.resolve_behavior_label
    )

    detector = YOLO(str(detector_path))

    verifier_model = (
        YOLO(str(verifier_path))
        if verifier_path
        else None
    )

    behavior_model = YOLO(
        str(behavior_model_path)
    )

    behavior_specialist = YOLO(
        str(behavior_specialist_path)
    )

    capture = cv2.VideoCapture(
        str(input_path)
    )

    if not capture.isOpened():
        raise RuntimeError(
            f"입력 영상을 열 수 없습니다: {input_path}"
        )

    fps = (
        capture.get(cv2.CAP_PROP_FPS)
        or 30.0
    )

    width = int(
        capture.get(
            cv2.CAP_PROP_FRAME_WIDTH
        )
    )

    height = int(
        capture.get(
            cv2.CAP_PROP_FRAME_HEIGHT
        )
    )

    history = max(
        min_history,
        int(round(fps * window_seconds)),
    )

    states: dict[int, Any] = {}

    track_counts: dict[
        int,
        collections.Counter[str],
    ] = collections.defaultdict(
        collections.Counter
    )

    first_seen_frame: dict[int, int] = {}
    last_seen_frame: dict[int, int] = {}

    untracked_detections = 0
    processed_frames = 0

    try:
        while True:
            ok, frame = capture.read()

            if not ok:
                break

            result = detector.track(
                frame,
                persist=True,
                tracker=tracker,
                conf=conf,
                iou=iou,
                imgsz=imgsz,
                classes=classes or [0],
                verbose=False,
            )[0]

            if (
                result.boxes is None
                or not len(result.boxes)
            ):
                processed_frames += 1
                continue

            boxes = (
                result.boxes.xyxy
                .cpu()
                .numpy()
            )

            ids = (
                result.boxes.id
                .int()
                .cpu()
                .tolist()
                if result.boxes.id is not None
                else [
                    -(index + 1)
                    for index
                    in range(len(boxes))
                ]
            )

            keep = [True] * len(boxes)

            if verifier_model is not None:
                crops = []
                crop_indices = []

                for index, box in enumerate(
                    boxes
                ):
                    x1, y1, x2, y2 = (
                        box.tolist()
                    )

                    crop = frame[
                        max(0, int(y1)):
                        min(height, int(y2)),
                        max(0, int(x1)):
                        min(width, int(x2)),
                    ]

                    if crop.size:
                        crops.append(crop)
                        crop_indices.append(
                            index
                        )
                    else:
                        keep[index] = False

                if crops:
                    verifier_results = (
                        verifier_model.predict(
                            crops,
                            imgsz=verifier_imgsz,
                            verbose=False,
                        )
                    )

                    for (
                        index,
                        prediction,
                    ) in zip(
                        crop_indices,
                        verifier_results,
                    ):
                        if prediction.probs is None:
                            keep[index] = False
                            continue

                        top1 = int(
                            prediction.probs.top1
                        )

                        label = str(
                            prediction.names[top1]
                        ).lower()

                        score = float(
                            prediction.probs.top1conf
                        )

                        keep[index] = (
                            label == "hanwoo"
                            and score
                            >= verifier_conf
                        )

            behavior_crops = []
            behavior_indices = []

            for index, box in enumerate(boxes):
                if not keep[index]:
                    continue

                x1, y1, x2, y2 = box.tolist()

                crop = frame[
                    max(0, int(y1)):
                    min(height, int(y2)),
                    max(0, int(x1)):
                    min(width, int(x2)),
                ]

                if crop.size:
                    behavior_crops.append(crop)
                    behavior_indices.append(
                        index
                    )

            behavior_labels: dict[
                int,
                str,
            ] = {}

            if behavior_crops:
                base_predictions = (
                    behavior_model.predict(
                        behavior_crops,
                        imgsz=behavior_imgsz,
                        verbose=False,
                    )
                )

                specialist_predictions = (
                    behavior_specialist.predict(
                        behavior_crops,
                        imgsz=behavior_imgsz,
                        verbose=False,
                    )
                )

                for (
                    box_index,
                    prediction,
                    specialist_prediction,
                ) in zip(
                    behavior_indices,
                    base_predictions,
                    specialist_predictions,
                ):
                    if prediction.probs is None:
                        continue

                    behavior_label = (
                        prediction.names[
                            int(
                                prediction.probs.top1
                            )
                        ]
                    )

                    if (
                        specialist_prediction.probs
                        is not None
                    ):
                        specialist_label = (
                            specialist_prediction
                            .names[
                                int(
                                    specialist_prediction
                                    .probs.top1
                                )
                            ]
                        )

                        specialist_score = float(
                            specialist_prediction
                            .probs.top1conf
                        )

                        if (
                            specialist_label
                            == "feeding"
                            and specialist_score
                            >= feeding_threshold
                        ):
                            behavior_label = (
                                "feeding"
                            )

                        elif (
                            specialist_label
                            == "walking"
                            and specialist_score
                            >= walking_threshold
                        ):
                            behavior_label = (
                                "walking"
                            )

                    behavior_labels[
                        box_index
                    ] = behavior_label

            for index, (box, track_id) in enumerate(
                zip(boxes, ids)
            ):
                if not keep[index]:
                    continue

                # ByteTrack ID가 없는 detection은
                # 개체별 시간 누적에 사용할 수 없다.
                if track_id < 0:
                    untracked_detections += 1
                    continue

                x1, y1, x2, y2 = box.tolist()

                bw = x2 - x1
                bh = y2 - y1

                center = (
                    (x1 + x2) / 2,
                    (y1 + y2) / 2,
                    math.hypot(bw, bh),
                )

                state = states.setdefault(
                    track_id,
                    TrackState(
                        collections.deque(
                            maxlen=history
                        ),
                        collections.deque(
                            maxlen=history
                        ),
                        collections.deque(
                            maxlen=history
                        ),
                    ),
                )

                state.centers.append(center)

                state.aspects.append(
                    bw / max(bh, 1.0)
                )

                if index in behavior_labels:
                    state.labels.append(
                        behavior_labels[index]
                    )

                if state.labels:
                    state.last_label = (
                        collections.Counter(
                            state.labels
                        )
                        .most_common(1)[0][0]
                    )

                    motion_label = (
                        classify_motion(
                            state,
                            min_history,
                            move_threshold,
                            lying_ratio,
                        )
                    )

                    state.last_label = (
                        resolve_behavior_label(
                            state.last_label,
                            motion_label,
                        )
                    )

                label = state.last_label

                track_counts[
                    track_id
                ][label] += 1

                first_seen_frame.setdefault(
                    track_id,
                    processed_frames,
                )

                last_seen_frame[
                    track_id
                ] = processed_frames

            processed_frames += 1

    finally:
        capture.release()

    tracks = []

    for track_id in sorted(track_counts):
        counts = track_counts[track_id]

        behavior_frames = {
            behavior: int(
                counts.get(behavior, 0)
            )
            for behavior
            in sorted(ANALYSIS_BEHAVIORS)
        }

        excluded_frames = {
            behavior: int(
                counts.get(behavior, 0)
            )
            for behavior
            in sorted(EXCLUDED_BEHAVIORS)
        }

        behavior_seconds = {
            behavior: round(
                frame_count / fps,
                3,
            )
            for behavior, frame_count
            in behavior_frames.items()
        }

        excluded_seconds = {
            behavior: round(
                frame_count / fps,
                3,
            )
            for behavior, frame_count
            in excluded_frames.items()
        }

        analyzable_frames = sum(
            behavior_frames.values()
        )

        analyzable_seconds = (
            analyzable_frames / fps
            if fps > 0
            else 0.0
        )

        behavior_ratios = {
            behavior: round(
                (
                    frame_count
                    / analyzable_frames
                )
                if analyzable_frames
                else 0.0,
                4,
            )
            for behavior, frame_count
            in behavior_frames.items()
        }

        tracks.append(
            {
                "track_id": track_id,
                "first_seen_frame":
                    first_seen_frame[
                        track_id
                    ],
                "last_seen_frame":
                    last_seen_frame[
                        track_id
                    ],
                "behavior_frames":
                    behavior_frames,
                "behavior_seconds":
                    behavior_seconds,
                "behavior_ratios":
                    behavior_ratios,
                "excluded_frames":
                    excluded_frames,
                "excluded_seconds":
                    excluded_seconds,
                "analyzable_seconds":
                    round(
                        analyzable_seconds,
                        3,
                    ),
            }
        )

    return {
        "source": str(input_path),
        "fps": float(fps),
        "processed_frames":
            processed_frames,
        "duration_seconds": round(
            processed_frames / fps,
            3,
        )
        if fps > 0
        else None,
        "tracked_cattle_count":
            len(tracks),
        "untracked_detections":
            untracked_detections,
        "analysis_behaviors": [
            "lying",
            "standing",
            "walking",
        ],
        "excluded_behaviors": [
            "feeding",
        ],
        "tracks": tracks,
    }

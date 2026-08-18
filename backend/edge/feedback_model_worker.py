from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import uuid
from collections import defaultdict
from pathlib import Path

import cv2
import httpx
import torch
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from ultralytics import YOLO


ROOT = Path(os.getenv("FEEDBACK_LEARNING_ROOT", "/home/azureuser/feedback-learning"))
EVENTS = ROOT / "events"
RUNS = ROOT / "runs"
CURRENT_MODEL = Path(os.getenv(
    "FEEDBACK_CURRENT_BEHAVIOR_MODEL",
    "/home/azureuser/models/detection/cow-model/hanwoo_behavior_anomaly_share_20260811/cow_behavior_v6_specialist_best.pt",
))
DETECTOR_MODEL = Path(os.getenv(
    "FEEDBACK_COW_DETECTOR_MODEL",
    "/home/azureuser/models/detection/cow-model/hanwoo_behavior_anomaly_share_20260811/hanwoo_detector_v5_best.pt",
))
LABELS = ("feeding", "lying", "standing", "walking")
MIN_EVENTS_PER_CLASS = int(os.getenv("FEEDBACK_MIN_EVENTS_PER_CLASS", "5"))
FRAMES_PER_VIDEO = int(os.getenv("FEEDBACK_FRAMES_PER_VIDEO", "12"))
TRAIN_EPOCHS = int(os.getenv("FEEDBACK_TRAIN_EPOCHS", "12"))
SECRET = os.getenv("FEEDBACK_GPU_TRAIN_SECRET", "")
LOCK = threading.Lock()


class TrainingSample(BaseModel):
    feedback_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    corrected_label: str
    media_url: str
    media_kind: str


class TrainingRequest(BaseModel):
    batch_id: str
    samples: list[TrainingSample]


app = FastAPI(title="COWOW feedback model trainer")


def require_secret(value: str | None) -> None:
    if not SECRET or not value or not __import__("hmac").compare_digest(value, SECRET):
        raise HTTPException(status_code=401, detail="invalid training secret")


def safe_event_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def download(url: str, destination: Path) -> None:
    with httpx.stream("GET", url, timeout=600, follow_redirects=True) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for chunk in response.iter_bytes():
                output.write(chunk)


def sampled_frames(path: Path, kind: str):
    if kind == "image":
        frame = cv2.imread(str(path))
        if frame is not None:
            yield frame
        return
    capture = cv2.VideoCapture(str(path))
    total = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    positions = [int(index * (total - 1) / max(1, FRAMES_PER_VIDEO - 1)) for index in range(FRAMES_PER_VIDEO)]
    try:
        for position in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, position)
            ok, frame = capture.read()
            if ok and frame is not None:
                yield frame
    finally:
        capture.release()


def largest_cow_crop(detector: YOLO, frame):
    result = detector.predict(frame, conf=0.25, imgsz=640, device=0, verbose=False)[0]
    if result.boxes is None or len(result.boxes) == 0:
        return None
    boxes = result.boxes.xyxy.cpu().numpy()
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    x1, y1, x2, y2 = boxes[int(areas.argmax())].astype(int)
    height, width = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    return frame[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else None


def ingest(samples: list[TrainingSample]) -> dict[str, int]:
    detector = YOLO(str(DETECTOR_MODEL))
    counts = defaultdict(int)
    ROOT.mkdir(parents=True, exist_ok=True)
    for sample in samples:
        if sample.corrected_label not in LABELS:
            continue
        event_dir = EVENTS / sample.corrected_label / safe_event_id(sample.event_id)
        if event_dir.exists() and any(event_dir.glob("*.jpg")):
            continue
        event_dir.mkdir(parents=True, exist_ok=True)
        media_path = event_dir / ("source.mp4" if sample.media_kind == "video" else "source.jpg")
        download(sample.media_url, media_path)
        for index, frame in enumerate(sampled_frames(media_path, sample.media_kind)):
            crop = largest_cow_crop(detector, frame)
            if crop is not None and crop.size:
                cv2.imwrite(str(event_dir / f"crop-{index:03d}.jpg"), crop)
                counts[sample.corrected_label] += 1
        media_path.unlink(missing_ok=True)
    return dict(counts)


def event_inventory() -> dict[str, list[Path]]:
    return {
        label: sorted(path for path in (EVENTS / label).glob("*") if any(path.glob("*.jpg")))
        for label in LABELS
    }


def build_dataset(batch_id: str, inventory: dict[str, list[Path]]) -> tuple[Path, list[tuple[Path, str]]]:
    dataset = RUNS / batch_id / "dataset"
    validation = []
    for label, events in inventory.items():
        for event_index, event_dir in enumerate(events):
            split = "val" if event_index % 5 == 0 else "train"
            target = dataset / split / label
            target.mkdir(parents=True, exist_ok=True)
            for image in event_dir.glob("*.jpg"):
                destination = target / f"{event_dir.name}-{image.name}"
                shutil.copy2(image, destination)
                if split == "val":
                    validation.append((destination, label))
    return dataset, validation


def evaluate(model_path: Path, samples: list[tuple[Path, str]]) -> dict:
    model = YOLO(str(model_path))
    correct = defaultdict(int)
    total = defaultdict(int)
    for image, label in samples:
        result = model.predict(str(image), device=0, verbose=False)[0]
        predicted = result.names[int(result.probs.top1)]
        total[label] += 1
        correct[label] += int(predicted == label)
    recall = {label: correct[label] / total[label] if total[label] else 0.0 for label in LABELS}
    overall = sum(correct.values()) / max(1, sum(total.values()))
    balanced = sum(recall.values()) / len(LABELS)
    return {"accuracy": round(overall, 4), "balanced_accuracy": round(balanced, 4), "recall": recall, "count": sum(total.values())}


def train(batch_id: str) -> dict:
    inventory = event_inventory()
    event_counts = {label: len(events) for label, events in inventory.items()}
    if any(count < MIN_EVENTS_PER_CLASS for count in event_counts.values()):
        return {"status": "collecting", "event_counts": event_counts, "required_per_class": MIN_EVENTS_PER_CLASS, "promoted": False}
    dataset, validation = build_dataset(batch_id, inventory)
    run_dir = RUNS / batch_id
    model = YOLO(str(CURRENT_MODEL))
    result = model.train(
        data=str(dataset), epochs=TRAIN_EPOCHS, imgsz=224, batch=32,
        device=0, workers=4, project=str(run_dir), name="candidate",
        patience=5, cache="disk", verbose=False,
    )
    candidate = Path(result.save_dir) / "weights" / "best.pt"
    baseline_metrics = evaluate(CURRENT_MODEL, validation)
    candidate_metrics = evaluate(candidate, validation)
    recalls_ok = all(
        candidate_metrics["recall"][label] >= baseline_metrics["recall"][label] - 0.05
        for label in LABELS
    )
    passed = (
        candidate_metrics["balanced_accuracy"] >= baseline_metrics["balanced_accuracy"]
        and candidate_metrics["accuracy"] >= baseline_metrics["accuracy"]
        and recalls_ok
    )
    promoted = False
    if passed and os.getenv("FEEDBACK_AUTO_PROMOTE", "false").lower() == "true":
        backup = ROOT / "model-backups" / f"behavior-{batch_id}.pt"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CURRENT_MODEL, backup)
        temporary = CURRENT_MODEL.with_suffix(".candidate.pt")
        shutil.copy2(candidate, temporary)
        temporary.replace(CURRENT_MODEL)
        subprocess.run(["sudo", "-n", "systemctl", "restart", "realtime-inference.service"], check=True)
        promoted = True
    metrics = {"passed": passed, "baseline": baseline_metrics, "candidate": candidate_metrics, "event_counts": event_counts}
    (run_dir / "evaluation.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return {"status": "trained", "candidate_model_path": str(candidate), "metrics": metrics, "promoted": promoted}


@app.get("/health")
def health():
    return {"status": "ok", "cuda": torch.cuda.is_available(), "current_model": str(CURRENT_MODEL)}


@app.post("/run")
def run_training(request: TrainingRequest, x_feedback_training_secret: str | None = Header(default=None)):
    require_secret(x_feedback_training_secret)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="training already running")
    try:
        ingested = ingest(request.samples)
        result = train(request.batch_id)
        return {**result, "ingested": ingested}
    finally:
        LOCK.release()

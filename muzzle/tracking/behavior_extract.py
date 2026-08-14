#!/usr/bin/env python3
"""한우 검출 + ByteTrack + 행동 분류 → JSONL.

이상행동 파트의 cow_pipeline.py track() 이 화면에만 그리고 버리는 값
(track_id · 행동 · bbox · 프레임번호)을 데이터로 뽑는다. 검출·추적·행동
로직은 그쪽 코드를 그대로 재사용하고, 이 파일은 적재 가능한 형태로
바꾸는 층만 담당한다.

DB 에 직접 쓰지 않는다 — track_load.py 와 짝을 이룬다.
GPU VM 에 DB 자격증명을 두지 않기 위한 분리다.

cow_pipeline.py 는 상단에서 azureml.fsspec 을 import 하지만 track() 은
쓰지 않는다. 진짜 패키지를 설치하는 대신 가짜 모듈을 sys.modules 에 미리
등록해 우회한다 — 운영 중인 venv 의 의존성을 바꾸지 않기 위해서다.
"""
import argparse
import collections
import json
import math
import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

import cv2

PKG = os.getenv(
    "BEHAVIOR_PKG_DIR",
    "/home/azureuser/models/detection/cow-model/hanwoo_behavior_anomaly_share_20260811",
)

# --- azureml 스텁 (import 전에 등록해야 한다) -------------------------------
for name in ("azureml", "azureml.fsspec"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["azureml.fsspec"].AzureMachineLearningFileSystem = object
sys.modules["azureml"].fsspec = sys.modules["azureml.fsspec"]
# ---------------------------------------------------------------------------

sys.path.insert(0, PKG)
import cow_pipeline as P   # noqa: E402  평활화 로직 재사용
from ultralytics import YOLO   # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--camera", default="A")
    p.add_argument("--session", default=None)
    p.add_argument("--session-prefix", default="",
                   help="test_ 는 timeline 기본 응답에서 제외된다")
    p.add_argument("--start-time", default=None,
                   help="0프레임 기준 시각(ISO8601). 카메라 간 핸드오프를 하려면 "
                        "두 영상에 같은 값을 줘야 한다")
    p.add_argument("--weights", default=f"{PKG}/hanwoo_detector_v5_best.pt")
    p.add_argument("--behavior-weights", default=f"{PKG}/cow_behavior_v5_best.pt")
    p.add_argument("--behavior-specialist-weights",
                   default=f"{PKG}/cow_behavior_v6_specialist_best.pt")
    p.add_argument("--tracker", default="bytetrack.yaml")
    p.add_argument("--conf", type=float, default=0.05)
    p.add_argument("--iou", type=float, default=0.45)
    p.add_argument("--imgsz", type=int, default=960)
    p.add_argument("--behavior-imgsz", type=int, default=224)
    p.add_argument("--classes", type=int, nargs="+", default=[0])
    p.add_argument("--feeding-threshold", type=float, default=0.85)
    p.add_argument("--walking-threshold", type=float, default=0.55)
    p.add_argument("--window-seconds", type=float, default=1.0)
    p.add_argument("--min-history", type=int, default=5)
    p.add_argument("--move-threshold", type=float, default=0.12)
    p.add_argument("--lying-ratio", type=float, default=1.75)
    p.add_argument("--stride", type=int, default=1, help="N프레임마다 1장 처리")
    p.add_argument("--max-frames", type=int, default=0, help="0=전체")
    a = p.parse_args()

    session_id = a.session or (a.session_prefix
                               + datetime.now().strftime("%Y%m%d%H%M%S")
                               + "-" + uuid.uuid4().hex[:6])
    base = (datetime.fromisoformat(a.start_time)
            if a.start_time else datetime.now(timezone.utc))
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    model = YOLO(a.weights)
    behavior_model = YOLO(a.behavior_weights)
    specialist = YOLO(a.behavior_specialist_weights)

    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        sys.exit(f"영상을 열 수 없다: {a.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    history = max(a.min_history, int(round(fps * a.window_seconds)))

    states, written, processed, frame_no = {}, 0, 0, 0
    counts = collections.Counter()

    with open(a.out, "w") as f:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx = frame_no
            frame_no += 1
            if a.stride > 1 and idx % a.stride:
                continue

            r = model.track(frame, persist=True, tracker=a.tracker, conf=a.conf,
                            iou=a.iou, imgsz=a.imgsz, classes=a.classes,
                            verbose=False)[0]
            processed += 1
            if r.boxes is None or not len(r.boxes) or r.boxes.id is None:
                continue

            boxes = r.boxes.xyxy.cpu().numpy()
            ids = r.boxes.id.int().cpu().tolist()
            confs = r.boxes.conf.cpu().tolist()

            crops, cidx = [], []
            for i, b in enumerate(boxes):
                x1, y1, x2, y2 = b.tolist()
                c = frame[max(0, int(y1)):min(H, int(y2)),
                          max(0, int(x1)):min(W, int(x2))]
                if c.size:
                    crops.append(c)
                    cidx.append(i)
            if not crops:
                continue

            base_pred = behavior_model.predict(crops, imgsz=a.behavior_imgsz, verbose=False)
            spec_pred = specialist.predict(crops, imgsz=a.behavior_imgsz, verbose=False)

            labels, scores = {}, {}
            for i, bp, sp in zip(cidx, base_pred, spec_pred):
                if bp.probs is None:
                    continue
                lab = bp.names[int(bp.probs.top1)]
                sc = float(bp.probs.top1conf)
                if sp is not None and sp.probs is not None:
                    sl = sp.names[int(sp.probs.top1)]
                    ss = float(sp.probs.top1conf)
                    if sl == "feeding" and ss >= a.feeding_threshold:
                        lab, sc = "feeding", ss
                    elif sl == "walking" and ss >= a.walking_threshold:
                        lab, sc = "walking", ss
                labels[i], scores[i] = lab, sc

            ts = (base + timedelta(seconds=idx / fps)).isoformat()

            for i, (b, tid, cf) in enumerate(zip(boxes, ids, confs)):
                x1, y1, x2, y2 = b.tolist()
                bw, bh = x2 - x1, y2 - y1
                st = states.setdefault(tid, P.TrackState(
                    collections.deque(maxlen=history),
                    collections.deque(maxlen=history),
                    collections.deque(maxlen=history)))
                st.centers.append(((x1 + x2) / 2, (y1 + y2) / 2, math.hypot(bw, bh)))
                st.aspects.append(bw / max(bh, 1.0))
                if i in labels:
                    st.labels.append(labels[i])
                if st.labels:
                    st.last_label = collections.Counter(st.labels).most_common(1)[0][0]
                    motion = P.classify_motion(st, a.min_history, a.move_threshold,
                                               a.lying_ratio)
                    st.last_label = P.resolve_behavior_label(st.last_label, motion)
                counts[st.last_label] += 1

                f.write(json.dumps({
                    "camera_id": a.camera,
                    "session_id": session_id,
                    "track_id": int(tid),
                    "ts": ts,
                    "frame_idx": idx,
                    "bbox_x": x1, "bbox_y": y1, "bbox_w": bw, "bbox_h": bh,
                    "conf": float(cf),
                    "behavior": st.last_label,
                    "behavior_conf": round(scores.get(i, 0.0), 4),
                    "source_video": a.video,
                }) + "\n")
                written += 1

            if a.max_frames and processed >= a.max_frames:
                break

    cap.release()
    print(f"session_id : {session_id}")
    print(f"기준 시각  : {base.isoformat()}")
    print(f"처리 프레임: {processed} / 읽은 프레임 {frame_no}")
    print(f"관측 기록  : {written}건 → {a.out}")
    print(f"행동 분포  : {dict(counts)}")


if __name__ == "__main__":
    main()

"""영상 → YOLO+ByteTrack 추적 → JSONL.

DB에 직접 쓰지 않는다. 추론과 적재를 분리해 두면
추적을 모델 전용 VM에서 돌릴 때 DB 자격증명이 필요 없다.
"""
import argparse, json, uuid
from datetime import datetime, timezone, timedelta

import cv2
from ultralytics import YOLO

p = argparse.ArgumentParser()
p.add_argument("--video", required=True)
p.add_argument("--out", required=True)
p.add_argument("--camera", default="A")
p.add_argument("--weights", default="yolov8s.pt")
p.add_argument("--classes", default="19", help="COCO cow=19. 전체는 빈 문자열")
p.add_argument("--conf", type=float, default=0.25)
p.add_argument("--stride", type=int, default=5)
p.add_argument("--max-frames", type=int, default=120)
p.add_argument("--session", default=None,
               help="세션 ID 직접 지정")
p.add_argument("--session-prefix", default="",
               help="자동 생성 세션 ID 앞에 붙일 접두어. test_ 는 timeline 기본 응답에서 제외된다")
a = p.parse_args()

classes = [int(x) for x in a.classes.split(",")] if a.classes.strip() else None

cap = cv2.VideoCapture(a.video)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
cap.release()

session_id = a.session or (a.session_prefix
                           + datetime.now().strftime("%Y%m%d%H%M%S")
                           + "-" + uuid.uuid4().hex[:6])
base = datetime.now(timezone.utc)

model = YOLO(a.weights)
kept = written = 0

with open(a.out, "w") as f:
    for i, r in enumerate(model.track(
            source=a.video, persist=True, tracker="bytetrack.yaml",
            conf=a.conf, classes=classes, vid_stride=a.stride,
            stream=True, verbose=False)):
        b = r.boxes
        if b is None or b.id is None:
            continue
        frame_idx = i * a.stride
        ts = (base + timedelta(seconds=frame_idx / fps)).isoformat()
        xyxy = b.xyxy.cpu().numpy()
        ids = b.id.int().cpu().numpy()
        cf = b.conf.cpu().numpy()
        for k in range(len(ids)):
            x1, y1, x2, y2 = (float(v) for v in xyxy[k])
            f.write(json.dumps({
                "camera_id": a.camera,
                "session_id": session_id,
                "track_id": int(ids[k]),
                "ts": ts,
                "frame_idx": frame_idx,
                "bbox_x": x1, "bbox_y": y1,
                "bbox_w": x2 - x1, "bbox_h": y2 - y1,
                "conf": float(cf[k]),
                "source_video": a.video,
            }) + "\n")
            written += 1
        kept += 1
        if a.max_frames and kept >= a.max_frames:
            break

print(f"session_id={session_id}  프레임={kept}  관측={written}  →  {a.out}")
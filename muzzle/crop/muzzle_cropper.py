"""코 크롭 — hanwoo_muzzle_v2.ipynb 셀 29 이식.
   YOLO-World zero-shot / margin 0.15 / conf 0.02
   CFF 교차 데이터셋에서 검출률 0.9925 검증됨.
   반환은 BGR (encoder_onnx.py 입력 규격과 일치)."""
import cv2, numpy as np
import torch
from ultralytics import YOLOWorld

class MuzzleCropper:
    def __init__(self, weights="yolov8x-worldv2.pt"):
        self.world = YOLOWorld(weights)
        self.world.set_classes(["cow nose", "cattle muzzle", "animal nose"])

    def crop(self, path_or_bgr, margin=0.15, conf=0.02, max_side=1280):
        """성공 시 BGR 크롭 ndarray, 실패 시 None"""
        im = cv2.imread(path_or_bgr) if isinstance(path_or_bgr, str) else path_or_bgr
        if im is None: return None
        h, w = im.shape[:2]
        s = min(1.0, max_side / max(h, w))
        small = cv2.resize(im, (int(w*s), int(h*s))) if s < 1 else im
        device = (
            0
            if torch.cuda.is_available()
            else "cpu"
        )

        r = self.world.predict(
            small,
            conf=conf,
            device=device,
            verbose=False,
        )[0]
        if len(r.boxes) == 0: return None
        b = r.boxes.xyxy[int(r.boxes.conf.argmax())].cpu().numpy() / s
        bw, bh = b[2]-b[0], b[3]-b[1]
        x1, y1 = int(max(0, b[0]-bw*margin)), int(max(0, b[1]-bh*margin))
        x2, y2 = int(min(w, b[2]+bw*margin)), int(min(h, b[3]+bh*margin))
        c = im[y1:y2, x1:x2]
        return c if c.size else None

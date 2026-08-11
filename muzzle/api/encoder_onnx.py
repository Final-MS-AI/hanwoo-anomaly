"""
비문 임베딩 인코더 — ONNX 추론판
전처리는 models/muzzle/muzzle_encoder.py 와 완전히 동일하게 유지한다.
gray -> CLAHE(2.0, 8x8) -> 3채널 복제 -> Resize(255) -> CenterCrop(224)
-> ToTensor -> ImageNet Normalize -> ONNX -> L2 정규화
★ 임의로 고치지 말 것. 학습 조건과 어긋나면 정확도가 무너진다.
"""
import numpy as np, cv2, onnxruntime as ort
from PIL import Image

ONNX_PATH = "/home/azureuser/models/muzzle/weights/muzzle_encoder.onnx"
IMG_SIZE = 224
RESIZE = int(IMG_SIZE * 1.14)          # 255
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
DEFAULT_THRESHOLD = 0.45
MODEL_VERSION = "muzzle_onnx_gray_clahe_v1"


class MuzzleEncoderONNX:
    def __init__(self, onnx_path: str = ONNX_PATH):
        self.sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        self.in_name = self.sess.get_inputs()[0].name
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def _preprocess(self, img_bytes: bytes) -> np.ndarray:
        buf = np.frombuffer(img_bytes, np.uint8)
        bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("이미지를 디코딩할 수 없습니다")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        # GRAY=True, CLAHE=True (run_manifest 기준)
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        g = self._clahe.apply(g)
        rgb = np.stack([g, g, g], -1)

        # torchvision Resize(int) 와 동일: 짧은 변을 255로, 비율 유지
        pil = Image.fromarray(rgb)
        w, h = pil.size
        if w < h:
            nw, nh = RESIZE, int(round(RESIZE * h / w))
        else:
            nh, nw = RESIZE, int(round(RESIZE * w / h))
        pil = pil.resize((nw, nh), Image.BILINEAR)

        left, top = (nw - IMG_SIZE) // 2, (nh - IMG_SIZE) // 2
        pil = pil.crop((left, top, left + IMG_SIZE, top + IMG_SIZE))

        arr = np.asarray(pil, np.float32) / 255.0
        arr = (arr - MEAN) / STD
        return arr.transpose(2, 0, 1)      # HWC -> CHW

    def embed(self, images) -> np.ndarray:
        batch = np.stack([self._preprocess(b) for b in images]).astype(np.float32)
        v = self.sess.run(None, {self.in_name: batch})[0]
        return (v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)).astype(np.float32)

    def enroll(self, images) -> np.ndarray:
        """사진 여러 장 -> 평균 임베딩 1개. 원본 모듈과 동일한 방식."""
        v = self.embed(images).mean(0)
        return (v / (np.linalg.norm(v) + 1e-12)).astype(np.float32)

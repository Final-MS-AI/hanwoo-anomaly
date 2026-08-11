"""
한우 비문 개체식별 — 임베딩 인코더 추론 모듈
=============================================
학습: Zenodo Beef Cattle Muzzle DB (268두 / 4,923장), EfficientNet-B0 + ArcFace
평가: 미학습 67두 개방집합, Top-1 0.9794

백엔드에서 쓰는 법:
    from muzzle_encoder import MuzzleEncoder
    enc = MuzzleEncoder("muzzle_encoder.pt")

    vec  = enc.enroll(["cow1_a.jpg", "cow1_b.jpg", "cow1_c.jpg"])  # 등록: 512차원 벡터 1개
    cow_id, score = enc.identify("query.jpg", gallery)             # 조회: (개체ID or None, 유사도)

전제: 입력 이미지는 '코 부위만 잘린' 크롭이다.
      원본 사진에서 코를 찾아 자르는 건 검출(YOLO) 담당 몫이고 이 모듈은 하지 않는다.

의존성: torch, timm, opencv-python, numpy, pillow
"""

import numpy as np
import cv2
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms as T
import timm

# 학습 시 사용한 운영 임계값. 근거: openset_results.csv
#   threshold 0.40 → 오배정률 0.0000 / 보류율 0.0236 / 커버리지 내 정확도 1.0000
DEFAULT_THRESHOLD = 0.40

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class _Encoder(nn.Module):
    """학습 때와 반드시 동일한 구조여야 가중치가 로드된다."""

    def __init__(self, model_name: str, embed_dim: int):
        super().__init__()
        self.backbone = timm.create_model(model_name, pretrained=False, num_classes=0)
        d = self.backbone.num_features
        self.neck = nn.Sequential(
            nn.BatchNorm1d(d),
            nn.Dropout(0.2),
            nn.Linear(d, embed_dim),
            nn.BatchNorm1d(embed_dim),
        )

    def forward(self, x):
        return self.neck(self.backbone(x))


class MuzzleEncoder:
    def __init__(self, ckpt_path: str, device: str = None, threshold: float = DEFAULT_THRESHOLD):
        ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        self.cfg = ck["cfg"]
        self.threshold = threshold
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.model = _Encoder(self.cfg["model"], self.cfg["embed_dim"])
        self.model.load_state_dict(ck["enc"])
        self.model.eval().to(self.device)

        size = self.cfg["img_size"]
        self.tf = T.Compose([
            T.Resize(int(size * 1.14)),
            T.CenterCrop(size),
            T.ToTensor(),
            T.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ])
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    # ------------------------------------------------------------------
    # 전처리 — ★ 학습과 달라지면 안 됨. 임의로 고치지 말 것.
    # ------------------------------------------------------------------
    def _preprocess(self, img):
        """img: 파일 경로(str) 또는 RGB numpy 배열"""
        if isinstance(img, str):
            bgr = cv2.imread(img)
            if bgr is None:
                raise FileNotFoundError(img)
            img = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = np.asarray(img)

        if self.cfg["GRAY"]:
            g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            if self.cfg["CLAHE"]:
                g = self._clahe.apply(g)
            img = np.stack([g, g, g], -1)  # ImageNet 사전학습이 3채널을 요구해 복제

        return self.tf(Image.fromarray(img))

    # ------------------------------------------------------------------
    @torch.no_grad()
    def embed(self, images, batch_size: int = 32) -> np.ndarray:
        """이미지 리스트 → L2 정규화된 (N, 512) 임베딩"""
        if not isinstance(images, (list, tuple)):
            images = [images]
        out = []
        for i in range(0, len(images), batch_size):
            batch = torch.stack([self._preprocess(x) for x in images[i:i + batch_size]])
            v = self.model(batch.to(self.device))
            out.append(F.normalize(v, dim=1).cpu().numpy())
        return np.concatenate(out).astype(np.float32)

    def enroll(self, images) -> np.ndarray:
        """개체 등록. 사진 3~5장 → 평균 임베딩 1개 (512,). 이걸 DB에 저장한다."""
        v = self.embed(images).mean(0)
        return (v / (np.linalg.norm(v) + 1e-12)).astype(np.float32)

    def identify(self, image, gallery: dict, threshold: float = None):
        """
        조회. gallery = {개체ID: 등록임베딩(512,)}
        반환 (개체ID, 유사도). 유사도가 임계값 미만이면 (None, 유사도) = '미확정' 보류.
        """
        thr = self.threshold if threshold is None else threshold
        if not gallery:
            return None, 0.0
        ids = list(gallery.keys())
        G = np.stack([gallery[k] for k in ids])
        sim = self.embed(image)[0] @ G.T
        j = int(sim.argmax())
        best = float(sim[j])
        return (ids[j] if best >= thr else None), best


if __name__ == "__main__":
    import sys
    enc = MuzzleEncoder(sys.argv[1] if len(sys.argv) > 1 else "muzzle_encoder.pt")
    print("로드 성공")
    print("  백본     :", enc.cfg["model"])
    print("  입력     :", enc.cfg["img_size"], "x", enc.cfg["img_size"],
          "| GRAY:", enc.cfg["GRAY"], "| CLAHE:", enc.cfg["CLAHE"])
    print("  임베딩   :", enc.cfg["embed_dim"], "차원")
    print("  임계값   :", enc.threshold)
    dummy = np.random.randint(0, 255, (300, 300, 3), dtype=np.uint8)
    print("  출력 확인:", enc.embed([dummy]).shape)

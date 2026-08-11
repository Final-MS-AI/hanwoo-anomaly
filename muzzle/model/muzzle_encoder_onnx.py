from __future__ import annotations

from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import onnxruntime as ort

# Python 환경에 설치된 CUDA·cuDNN 라이브러리를
# ONNX Runtime 세션 생성 전에 로드합니다.
ort.preload_dlls()


DEFAULT_MODEL_PATH = Path(
    "/home/azureuser/models/muzzle/weights/muzzle_encoder.onnx"
)

DEFAULT_THRESHOLD = 0.40
IMAGE_SIZE = 224

IMAGENET_MEAN = np.array(
    [0.485, 0.456, 0.406],
    dtype=np.float32,
).reshape(3, 1, 1)

IMAGENET_STD = np.array(
    [0.229, 0.224, 0.225],
    dtype=np.float32,
).reshape(3, 1, 1)


class MuzzleEncoderONNX:
    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL_PATH,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self.model_path = Path(model_path)
        self.threshold = threshold

        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"ONNX 모델 파일이 없습니다: {self.model_path}"
            )

        available_providers = (
            ort.get_available_providers()
        )

        providers = (
            [
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]
            if "CUDAExecutionProvider"
            in available_providers
            else ["CPUExecutionProvider"]
        )

        self.session = ort.InferenceSession(
            str(self.model_path),
            providers=providers,
        )

        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        self.clahe = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8),
        )

    def _load_rgb(
        self,
        image: str | Path | np.ndarray,
    ) -> np.ndarray:
        if isinstance(image, (str, Path)):
            bgr = cv2.imread(str(image))

            if bgr is None:
                raise FileNotFoundError(
                    f"이미지를 읽을 수 없습니다: {image}"
                )

            return cv2.cvtColor(
                bgr,
                cv2.COLOR_BGR2RGB,
            )

        array = np.asarray(image)

        if array.ndim != 3 or array.shape[2] != 3:
            raise ValueError(
                "입력 이미지는 H×W×3 형식이어야 합니다."
            )

        return array

    def _resize_center_crop(
        self,
        image: np.ndarray,
    ) -> np.ndarray:
        height, width = image.shape[:2]

        resize_short = int(IMAGE_SIZE * 1.14)
        scale = resize_short / min(height, width)

        resized_width = max(
            IMAGE_SIZE,
            int(round(width * scale)),
        )
        resized_height = max(
            IMAGE_SIZE,
            int(round(height * scale)),
        )

        resized = cv2.resize(
            image,
            (resized_width, resized_height),
            interpolation=cv2.INTER_LINEAR,
        )

        x1 = (resized_width - IMAGE_SIZE) // 2
        y1 = (resized_height - IMAGE_SIZE) // 2

        return resized[
            y1:y1 + IMAGE_SIZE,
            x1:x1 + IMAGE_SIZE,
        ]

    def preprocess(
        self,
        image: str | Path | np.ndarray,
    ) -> np.ndarray:
        rgb = self._load_rgb(image)

        gray = cv2.cvtColor(
            rgb,
            cv2.COLOR_RGB2GRAY,
        )

        gray = self.clahe.apply(gray)

        three_channel = np.stack(
            [gray, gray, gray],
            axis=-1,
        )

        cropped = self._resize_center_crop(
            three_channel
        )

        tensor = cropped.astype(np.float32) / 255.0
        tensor = np.transpose(
            tensor,
            (2, 0, 1),
        )

        tensor = (
            tensor - IMAGENET_MEAN
        ) / IMAGENET_STD

        return tensor.astype(np.float32)

    def embed(
        self,
        images: Iterable[str | Path | np.ndarray]
        | str
        | Path
        | np.ndarray,
    ) -> np.ndarray:
        if isinstance(images, (str, Path, np.ndarray)):
            image_list = [images]
        else:
            image_list = list(images)

        if not image_list:
            raise ValueError(
                "임베딩할 이미지가 없습니다."
            )

        batch = np.stack(
            [
                self.preprocess(image)
                for image in image_list
            ],
            axis=0,
        )

        embeddings = self.session.run(
            [self.output_name],
            {
                self.input_name: batch,
            },
        )[0]

        norms = np.linalg.norm(
            embeddings,
            axis=1,
            keepdims=True,
        )

        embeddings = embeddings / (
            norms + 1e-12
        )

        return embeddings.astype(np.float32)

    def enroll(
        self,
        images: Iterable[str | Path | np.ndarray],
    ) -> np.ndarray:
        embeddings = self.embed(images)
        vector = embeddings.mean(axis=0)

        return (
            vector
            / (np.linalg.norm(vector) + 1e-12)
        ).astype(np.float32)

    def identify(
        self,
        image: str | Path | np.ndarray,
        gallery: dict[str, np.ndarray],
        threshold: float | None = None,
    ) -> tuple[str | None, float]:
        if not gallery:
            return None, 0.0

        ids = list(gallery.keys())

        gallery_matrix = np.stack(
            [
                np.asarray(
                    gallery[cattle_id],
                    dtype=np.float32,
                )
                for cattle_id in ids
            ],
            axis=0,
        )

        query = self.embed(image)[0]
        similarities = query @ gallery_matrix.T

        best_index = int(
            similarities.argmax()
        )
        best_score = float(
            similarities[best_index]
        )

        applied_threshold = (
            self.threshold
            if threshold is None
            else threshold
        )

        cattle_id = (
            ids[best_index]
            if best_score >= applied_threshold
            else None
        )

        return cattle_id, best_score


if __name__ == "__main__":
    encoder = MuzzleEncoderONNX()

    print("ONNX 비문 인코더 로드 성공")
    print("모델:", encoder.model_path)
    print("입력 이름:", encoder.input_name)
    print("출력 이름:", encoder.output_name)
    print("입력 크기:", IMAGE_SIZE)
    print("임베딩 차원: 512")
    print("운영 임계값:", encoder.threshold)

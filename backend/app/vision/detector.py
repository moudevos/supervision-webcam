from __future__ import annotations

from time import perf_counter

import cv2
import numpy as np
import onnxruntime as ort
import supervision as sv

from app.core.config import settings


class PersonDetector:
    """YOLOX Nano detector focused only on the COCO `person` class."""

    input_size = (416, 416)
    strides = (8, 16, 32)
    person_class_id = 0

    def __init__(self) -> None:
        self.model_path = settings.resolved_model_path
        self.session: ort.InferenceSession | None = None
        self.input_name: str | None = None

        if self.model_path.exists():
            self._load_model()

    @property
    def ready(self) -> bool:
        return self.session is not None and self.input_name is not None

    def _load_model(self) -> None:
        self.session = ort.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name

    def detect(self, image: np.ndarray) -> tuple[list[dict], float]:
        if not self.ready:
            raise RuntimeError(
                "Detection model is not available. Run: python scripts/download_model.py"
            )

        started_at = perf_counter()
        tensor, ratio = self._preprocess(image)

        outputs = self.session.run(None, {self.input_name: tensor})
        predictions = self._decode_yolox(outputs[0])[0]

        boxes = predictions[:, :4]
        class_scores = predictions[:, 4:5] * predictions[:, 5:]

        scores = class_scores[:, self.person_class_id]
        keep = scores >= settings.confidence_threshold

        boxes = boxes[keep]
        scores = scores[keep]

        if boxes.size == 0:
            elapsed_ms = (perf_counter() - started_at) * 1000
            return [], elapsed_ms

        boxes_xyxy = np.empty_like(boxes)
        boxes_xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
        boxes_xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
        boxes_xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
        boxes_xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
        boxes_xyxy /= ratio

        image_height, image_width = image.shape[:2]
        boxes_xyxy[:, [0, 2]] = np.clip(boxes_xyxy[:, [0, 2]], 0, image_width - 1)
        boxes_xyxy[:, [1, 3]] = np.clip(boxes_xyxy[:, [1, 3]], 0, image_height - 1)

        detections = sv.Detections(
            xyxy=boxes_xyxy,
            confidence=scores.astype(np.float32),
            class_id=np.full(len(scores), self.person_class_id, dtype=int),
        ).with_nms(
            threshold=settings.nms_threshold,
            class_agnostic=True,
        )

        result = [
            {
                "class_name": "person",
                "class_id": self.person_class_id,
                "confidence": float(confidence),
                "box": tuple(float(value) for value in box),
            }
            for box, confidence in zip(detections.xyxy, detections.confidence)
        ]

        elapsed_ms = (perf_counter() - started_at) * 1000
        return result, elapsed_ms

    def _preprocess(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        target_height, target_width = self.input_size
        image_height, image_width = image.shape[:2]

        ratio = min(target_height / image_height, target_width / image_width)
        resized_width = int(image_width * ratio)
        resized_height = int(image_height * ratio)

        resized = cv2.resize(
            image,
            (resized_width, resized_height),
            interpolation=cv2.INTER_LINEAR,
        )

        padded = np.full((target_height, target_width, 3), 114, dtype=np.uint8)
        padded[:resized_height, :resized_width] = resized

        tensor = padded.transpose(2, 0, 1).astype(np.float32)
        tensor = np.ascontiguousarray(tensor)[None, ...]
        return tensor, ratio

    def _decode_yolox(self, output: np.ndarray) -> np.ndarray:
        grids = []
        expanded_strides = []

        for stride in self.strides:
            height = self.input_size[0] // stride
            width = self.input_size[1] // stride
            grid_y, grid_x = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
            grid = np.stack((grid_x, grid_y), axis=2).reshape(1, -1, 2)
            grids.append(grid)
            expanded_strides.append(
                np.full((*grid.shape[:2], 1), stride, dtype=np.float32)
            )

        grids_array = np.concatenate(grids, axis=1).astype(np.float32)
        strides_array = np.concatenate(expanded_strides, axis=1)

        decoded = output.copy()
        decoded[..., :2] = (decoded[..., :2] + grids_array) * strides_array
        decoded[..., 2:4] = np.exp(decoded[..., 2:4]) * strides_array
        return decoded


detector = PersonDetector()

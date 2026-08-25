from __future__ import annotations

from time import perf_counter

import cv2
import numpy as np
import onnxruntime as ort
import supervision as sv

from app.core.config import settings


class PersonDetector:
    """YOLOX Nano scene detector with person tracking input and selected objects."""

    input_size = (416, 416)
    strides = (8, 16, 32)
    person_class_id = 0
    cell_phone_class_id = 67

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
        people, _, elapsed_ms = self.detect_scene(image)
        return people, elapsed_ms

    def detect_scene(self, image: np.ndarray) -> tuple[list[dict], list[dict], float]:
        if not self.ready:
            raise RuntimeError(
                "Detection model is not available. Run: python scripts/download_model.py"
            )

        started_at = perf_counter()
        tensor, ratio = self._preprocess(image)
        outputs = self.session.run(None, {self.input_name: tensor})
        predictions = self._decode_yolox(outputs[0])[0]
        image_height, image_width = image.shape[:2]

        people = self._extract_class(
            predictions=predictions,
            class_id=self.person_class_id,
            class_name="person",
            threshold=settings.confidence_threshold,
            ratio=ratio,
            image_width=image_width,
            image_height=image_height,
            min_area_ratio=settings.min_box_area_ratio,
        )
        phones = self._extract_class(
            predictions=predictions,
            class_id=self.cell_phone_class_id,
            class_name="cell_phone",
            threshold=settings.phone_detection_threshold,
            ratio=ratio,
            image_width=image_width,
            image_height=image_height,
            min_area_ratio=0.0,
        )

        elapsed_ms = (perf_counter() - started_at) * 1000
        return people, phones, elapsed_ms

    def _extract_class(
        self,
        *,
        predictions: np.ndarray,
        class_id: int,
        class_name: str,
        threshold: float,
        ratio: float,
        image_width: int,
        image_height: int,
        min_area_ratio: float,
    ) -> list[dict]:
        if predictions.size == 0 or predictions.shape[1] <= 5 + class_id:
            return []

        class_scores = predictions[:, 4:5] * predictions[:, 5:]
        scores = class_scores[:, class_id]
        keep = scores >= threshold
        boxes = predictions[keep, :4]
        scores = scores[keep]

        if boxes.size == 0:
            return []

        boxes_xyxy = np.empty_like(boxes)
        boxes_xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
        boxes_xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
        boxes_xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
        boxes_xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
        boxes_xyxy /= ratio

        boxes_xyxy[:, [0, 2]] = np.clip(boxes_xyxy[:, [0, 2]], 0, image_width - 1)
        boxes_xyxy[:, [1, 3]] = np.clip(boxes_xyxy[:, [1, 3]], 0, image_height - 1)

        if min_area_ratio > 0:
            widths = np.maximum(0.0, boxes_xyxy[:, 2] - boxes_xyxy[:, 0])
            heights = np.maximum(0.0, boxes_xyxy[:, 3] - boxes_xyxy[:, 1])
            areas = widths * heights
            min_area = image_width * image_height * min_area_ratio
            area_keep = areas >= min_area
            boxes_xyxy = boxes_xyxy[area_keep]
            scores = scores[area_keep]

        if boxes_xyxy.size == 0:
            return []

        detections = sv.Detections(
            xyxy=boxes_xyxy,
            confidence=scores.astype(np.float32),
            class_id=np.full(len(scores), class_id, dtype=int),
        ).with_nms(
            threshold=settings.nms_threshold,
            class_agnostic=True,
        )

        return [
            {
                "class_name": class_name,
                "class_id": class_id,
                "confidence": float(confidence),
                "box": tuple(float(value) for value in box),
            }
            for box, confidence in zip(detections.xyxy, detections.confidence)
        ]

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

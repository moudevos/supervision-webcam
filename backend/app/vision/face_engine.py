from __future__ import annotations

import cv2
import numpy as np

from app.core.config import settings


class FaceEngine:
    """Local YuNet + SFace pipeline for face detection and embeddings."""

    def __init__(self) -> None:
        self.detector = None
        self.recognizer = None

        if self.models_available:
            self._load_models()

    @property
    def models_available(self) -> bool:
        return (
            settings.resolved_face_detector_model_path.exists()
            and settings.resolved_face_recognizer_model_path.exists()
        )

    @property
    def ready(self) -> bool:
        return self.detector is not None and self.recognizer is not None

    def _load_models(self) -> None:
        self.detector = cv2.FaceDetectorYN.create(
            str(settings.resolved_face_detector_model_path),
            "",
            (320, 320),
            settings.face_detection_threshold,
            settings.face_nms_threshold,
            5000,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            str(settings.resolved_face_recognizer_model_path),
            "",
        )

    def detect(self, image: np.ndarray) -> list[dict]:
        if not self.ready:
            return []

        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(image)

        if faces is None or len(faces) == 0:
            return []

        observations: list[dict] = []
        for face in faces:
            embedding = self._embedding(image, face)
            x, y, w, h = (float(value) for value in face[:4])
            observations.append(
                {
                    "box": (x, y, x + w, y + h),
                    "confidence": float(face[-1]),
                    "embedding": embedding,
                }
            )

        return observations

    def extract_single_embedding(self, image: np.ndarray) -> np.ndarray:
        observations = self.detect(image)

        if len(observations) == 0:
            raise ValueError("No se detectó ningún rostro. Mira de frente a la cámara.")

        if len(observations) > 1:
            raise ValueError(
                "Se detectó más de un rostro. Registra una persona a la vez."
            )

        return observations[0]["embedding"]

    def _embedding(self, image: np.ndarray, face: np.ndarray) -> np.ndarray:
        # YuNet appends detection confidence as the last value; SFace alignment
        # consumes bbox + 5 landmarks (14 values).
        aligned = self.recognizer.alignCrop(image, face[:-1])
        feature = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)

        norm = float(np.linalg.norm(feature))
        if norm <= 1e-12:
            raise ValueError("No se pudo generar un embedding facial válido.")

        return feature / norm


face_engine = FaceEngine()

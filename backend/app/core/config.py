from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_path: str = "models/yolox_nano.onnx"

    # Detector: keep a low floor so ByteTrack can use weak detections
    # to recover an existing track. New IDs require a higher threshold
    # inside ByteTrack.
    confidence_threshold: float = 0.30
    nms_threshold: float = 0.45
    min_box_area_ratio: float = 0.0025

    # ByteTrack calibration for the current HTTP detection loop (~4 FPS).
    tracker_frame_rate: int = 4
    tracker_activation_threshold: float = 0.40
    tracker_lost_buffer: int = 90
    tracker_matching_threshold: float = 0.70
    tracker_min_consecutive_frames: int = 2

    # Temporal state shown by the UI.
    track_visible_grace_seconds: float = 2.0
    track_lost_threshold_seconds: float = 5.0
    track_retention_seconds: float = 5.0

    # Local face recognition.
    face_detector_model_path: str = "models/face_detection_yunet_2023mar.onnx"
    face_recognizer_model_path: str = "models/face_recognition_sface_2021dec.onnx"
    face_registry_path: str = "data/face_registry.json"
    face_detection_threshold: float = 0.85
    face_nms_threshold: float = 0.30
    face_match_threshold: float = 0.45
    face_scan_interval_frames: int = 4
    face_confirm_hits: int = 3
    face_max_samples_per_identity: int = 5

    # Presence persistence. SQLite is intentionally local for this MVP.
    presence_db_path: str = "data/presence.db"
    presence_persist_interval_seconds: float = 1.0
    presence_history_limit: int = 30
    presence_event_limit: int = 80

    # Zone persistence and dwell metrics.
    zone_persist_interval_seconds: float = 1.0
    zone_history_limit: int = 50
    zone_event_limit: int = 120

    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def backend_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def resolved_model_path(self) -> Path:
        return (self.backend_dir / self.model_path).resolve()

    @property
    def resolved_face_detector_model_path(self) -> Path:
        return (self.backend_dir / self.face_detector_model_path).resolve()

    @property
    def resolved_face_recognizer_model_path(self) -> Path:
        return (self.backend_dir / self.face_recognizer_model_path).resolve()

    @property
    def resolved_face_registry_path(self) -> Path:
        return (self.backend_dir / self.face_registry_path).resolve()

    @property
    def resolved_presence_db_path(self) -> Path:
        return (self.backend_dir / self.presence_db_path).resolve()

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

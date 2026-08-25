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

    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_model_path(self) -> Path:
        backend_dir = Path(__file__).resolve().parents[2]
        return (backend_dir / self.model_path).resolve()

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

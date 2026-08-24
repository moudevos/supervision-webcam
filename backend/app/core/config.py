from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_path: str = "models/yolox_nano.onnx"
    confidence_threshold: float = 0.45
    nms_threshold: float = 0.45
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

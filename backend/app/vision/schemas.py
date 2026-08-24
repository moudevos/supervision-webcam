from pydantic import BaseModel, Field


class DetectionItem(BaseModel):
    class_name: str
    class_id: int
    confidence: float = Field(ge=0.0, le=1.0)
    box: tuple[float, float, float, float]


class DetectionResponse(BaseModel):
    ready: bool
    image_width: int
    image_height: int
    inference_ms: float
    detections: list[DetectionItem]

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import cv2
import numpy as np

from app.core.config import settings
from app.vision.detector import detector
from app.vision.schemas import DetectionResponse
from app.vision.track_state import track_state_manager
from app.vision.tracker import tracker


app = FastAPI(title="Supervision Webcam API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "detector_ready": detector.ready,
        "model_path": str(detector.model_path),
        "tracking": "ByteTrack",
        "temporal_state": True,
    }


@app.post("/api/vision/tracking/reset")
def reset_tracking() -> dict:
    tracker.reset()
    track_state_manager.reset()
    return {"status": "ok"}


@app.post("/api/vision/detect", response_model=DetectionResponse)
async def detect(file: UploadFile = File(...)) -> DetectionResponse:
    if not detector.ready:
        raise HTTPException(
            status_code=503,
            detail="Detection model is not available. Run python scripts/download_model.py",
        )

    payload = await file.read()
    image_array = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image payload")

    detections, inference_ms = detector.detect(image)
    tracked_detections = tracker.update(detections)
    track_states = track_state_manager.update(tracked_detections)
    height, width = image.shape[:2]

    return DetectionResponse(
        ready=True,
        image_width=width,
        image_height=height,
        inference_ms=round(inference_ms, 2),
        detections=tracked_detections,
        tracks=track_states,
    )

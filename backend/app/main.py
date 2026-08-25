from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import cv2
import numpy as np

from app.core.config import settings
from app.presence.service import presence_manager
from app.vision.detector import detector
from app.vision.face_engine import face_engine
from app.vision.face_registry import face_registry
from app.vision.identity import identity_manager
from app.vision.schemas import (
    DetectionResponse,
    FaceRegistrationResponse,
    FaceRegistryResponse,
    PresenceHistoryResponse,
)
from app.vision.track_state import track_state_manager
from app.vision.tracker import tracker


app = FastAPI(title="Supervision Webcam API", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    face_diagnostics = face_engine.diagnostics()

    return {
        "status": "ok",
        "detector_ready": detector.ready,
        "model_path": str(detector.model_path),
        "tracking": "ByteTrack",
        "temporal_state": True,
        "face_recognition_ready": face_diagnostics["ready"],
        "face_registry_size": len(face_registry.list_people()),
        "face_models": face_diagnostics,
        "presence_history": {
            "enabled": True,
            "database_path": str(settings.resolved_presence_db_path),
        },
        "calibration": {
            "detection_floor": settings.confidence_threshold,
            "track_activation": settings.tracker_activation_threshold,
            "lost_buffer": settings.tracker_lost_buffer,
            "matching_threshold": settings.tracker_matching_threshold,
            "minimum_consecutive_frames": settings.tracker_min_consecutive_frames,
            "min_box_area_ratio": settings.min_box_area_ratio,
        },
    }


@app.get("/api/vision/faces", response_model=FaceRegistryResponse)
def list_faces() -> FaceRegistryResponse:
    return FaceRegistryResponse(
        ready=face_engine.ready,
        identities=face_registry.list_people(),
    )


@app.post("/api/vision/faces/register", response_model=FaceRegistrationResponse)
async def register_face(
    name: str = Form(...),
    file: UploadFile = File(...),
) -> FaceRegistrationResponse:
    if not face_engine.ready:
        detail = face_engine.load_error or (
            "Los modelos faciales no están disponibles. "
            "Ejecuta python scripts/download_model.py."
        )
        raise HTTPException(status_code=503, detail=detail)

    image = await decode_upload(file)

    try:
        embedding = face_engine.extract_single_embedding(image)
        registration = face_registry.add_sample(name, embedding)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    identity_manager.reset()
    return FaceRegistrationResponse(**registration)


@app.get("/api/presence/history", response_model=PresenceHistoryResponse)
def presence_history(
    session_limit: int = Query(default=30, ge=1, le=200),
    event_limit: int = Query(default=80, ge=1, le=500),
) -> PresenceHistoryResponse:
    history = presence_manager.history(session_limit, event_limit)
    return PresenceHistoryResponse(**history)


@app.post("/api/vision/tracking/reset")
def reset_tracking() -> dict:
    presence_manager.reset(close_reason="camera_reset")
    tracker.reset()
    track_state_manager.reset()
    identity_manager.reset()
    return {"status": "ok"}


@app.post("/api/vision/detect", response_model=DetectionResponse)
async def detect(file: UploadFile = File(...)) -> DetectionResponse:
    if not detector.ready:
        raise HTTPException(
            status_code=503,
            detail="Detection model is not available. Run python scripts/download_model.py",
        )

    image = await decode_upload(file)

    detections, inference_ms = detector.detect(image)
    tracked_detections = tracker.update(detections)
    track_states = track_state_manager.update(tracked_detections)
    track_states = identity_manager.update(image, tracked_detections, track_states)
    track_states = presence_manager.update(track_states)
    height, width = image.shape[:2]

    return DetectionResponse(
        ready=True,
        image_width=width,
        image_height=height,
        inference_ms=round(inference_ms, 2),
        detections=tracked_detections,
        tracks=track_states,
    )


async def decode_upload(file: UploadFile) -> np.ndarray:
    payload = await file.read()
    image_array = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image payload")

    return image

import "./styles.css";

const API_BASE_URL = "http://localhost:8000";
const DETECTION_URL = `${API_BASE_URL}/api/vision/detect`;
const TRACKING_RESET_URL = `${API_BASE_URL}/api/vision/tracking/reset`;
const DETECTION_INTERVAL_MS = 250;

const video = document.querySelector("#camera");
const overlay = document.querySelector("#overlay");
const ctx = overlay.getContext("2d");
const startButton = document.querySelector("#startButton");
const stopButton = document.querySelector("#stopButton");
const status = document.querySelector("#status");
const peopleCount = document.querySelector("#peopleCount");
const inferenceMs = document.querySelector("#inferenceMs");

let stream = null;
let loopId = null;
let requestInFlight = false;

const captureCanvas = document.createElement("canvas");
const captureContext = captureCanvas.getContext("2d");

async function startCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: "user"
      },
      audio: false
    });

    video.srcObject = stream;
    await video.play();
    await resetTracking();

    resizeCanvases();
    status.textContent = "Detectando";
    status.classList.add("status--active");
    startButton.disabled = true;
    stopButton.disabled = false;

    loopId = window.setInterval(runDetection, DETECTION_INTERVAL_MS);
  } catch (error) {
    console.error(error);
    status.textContent = error.message || "No se pudo abrir la cámara";
  }
}

function stopCamera() {
  if (loopId) {
    window.clearInterval(loopId);
    loopId = null;
  }

  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  video.srcObject = null;
  requestInFlight = false;

  void resetTracking();
  clearOverlay();
  peopleCount.textContent = "0";
  inferenceMs.textContent = "-";
  status.textContent = "Cámara apagada";
  status.classList.remove("status--active");
  startButton.disabled = false;
  stopButton.disabled = true;
}

async function resetTracking() {
  const response = await fetch(TRACKING_RESET_URL, { method: "POST" });
  if (!response.ok) {
    throw new Error(`No se pudo reiniciar tracking (${response.status})`);
  }
}

async function runDetection() {
  if (!stream || requestInFlight || video.readyState < 2) return;

  requestInFlight = true;

  try {
    captureCanvas.width = video.videoWidth;
    captureCanvas.height = video.videoHeight;
    captureContext.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);

    const blob = await canvasToBlob(captureCanvas, "image/jpeg", 0.72);
    const formData = new FormData();
    formData.append("file", blob, "frame.jpg");

    const response = await fetch(DETECTION_URL, {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || `API error ${response.status}`);
    }

    const result = await response.json();
    drawDetections(result);
    peopleCount.textContent = String(result.detections.length);
    inferenceMs.textContent = String(result.inference_ms);
    status.textContent = "Detectando";
  } catch (error) {
    console.error(error);
    status.textContent = error.message;
    clearOverlay();
  } finally {
    requestInFlight = false;
  }
}

function drawDetections(result) {
  clearOverlay();

  const scaleX = overlay.width / result.image_width;
  const scaleY = overlay.height / result.image_height;

  ctx.lineWidth = 3;
  ctx.strokeStyle = "#7cfc8a";
  ctx.fillStyle = "#7cfc8a";
  ctx.font = "600 16px system-ui";

  for (const detection of result.detections) {
    const [x1, y1, x2, y2] = detection.box;
    const x = x1 * scaleX;
    const y = y1 * scaleY;
    const width = (x2 - x1) * scaleX;
    const height = (y2 - y1) * scaleY;

    ctx.strokeRect(x, y, width, height);

    const idLabel = detection.tracker_id ?? "?";
    const label = `ID ${idLabel} · ${(detection.confidence * 100).toFixed(0)}%`;
    const textWidth = ctx.measureText(label).width;
    const labelY = Math.max(24, y);

    ctx.fillRect(x, labelY - 24, textWidth + 14, 24);
    ctx.fillStyle = "#07110a";
    ctx.fillText(label, x + 7, labelY - 7);
    ctx.fillStyle = "#7cfc8a";
  }
}

function resizeCanvases() {
  overlay.width = video.videoWidth;
  overlay.height = video.videoHeight;
  captureCanvas.width = video.videoWidth;
  captureCanvas.height = video.videoHeight;
}

function clearOverlay() {
  ctx.clearRect(0, 0, overlay.width, overlay.height);
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("No se pudo capturar el frame"));
    }, type, quality);
  });
}

startButton.addEventListener("click", startCamera);
stopButton.addEventListener("click", stopCamera);
window.addEventListener("resize", resizeCanvases);
window.addEventListener("beforeunload", stopCamera);

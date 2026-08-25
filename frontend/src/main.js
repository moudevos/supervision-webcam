import "./styles.css";

const API_BASE_URL = "http://localhost:8000";
const DETECTION_URL = `${API_BASE_URL}/api/vision/detect`;
const TRACKING_RESET_URL = `${API_BASE_URL}/api/vision/tracking/reset`;
const FACE_LIST_URL = `${API_BASE_URL}/api/vision/faces`;
const FACE_REGISTER_URL = `${API_BASE_URL}/api/vision/faces/register`;
const PRESENCE_HISTORY_URL = `${API_BASE_URL}/api/presence/history`;
const DETECTION_INTERVAL_MS = 250;
const HISTORY_REFRESH_MS = 3000;

const video = document.querySelector("#camera");
const overlay = document.querySelector("#overlay");
const ctx = overlay.getContext("2d");
const startButton = document.querySelector("#startButton");
const stopButton = document.querySelector("#stopButton");
const status = document.querySelector("#status");
const peopleCount = document.querySelector("#peopleCount");
const inferenceMs = document.querySelector("#inferenceMs");
const activeTracks = document.querySelector("#activeTracks");
const activeTrackCount = document.querySelector("#activeTrackCount");
const identityName = document.querySelector("#identityName");
const registerFaceButton = document.querySelector("#registerFaceButton");
const registrationStatus = document.querySelector("#registrationStatus");
const registeredIdentities = document.querySelector("#registeredIdentities");
const presenceHistory = document.querySelector("#presenceHistory");
const historyCount = document.querySelector("#historyCount");

let stream = null;
let loopId = null;
let requestInFlight = false;
let faceRecognitionReady = false;

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
    await refreshPresenceHistory();

    resizeCanvases();
    renderTrackedPeople([]);
    status.textContent = "Detectando";
    status.classList.add("status--active");
    startButton.disabled = true;
    stopButton.disabled = false;
    registerFaceButton.disabled = !faceRecognitionReady;

    if (faceRecognitionReady) {
      registrationStatus.textContent = "Escribe un nombre y mira de frente a la cámara.";
    }

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

  void resetTracking()
    .then(refreshPresenceHistory)
    .catch((error) => console.error(error));

  clearOverlay();
  renderTrackedPeople([]);
  peopleCount.textContent = "0";
  inferenceMs.textContent = "-";
  status.textContent = "Cámara apagada";
  status.classList.remove("status--active");
  startButton.disabled = false;
  stopButton.disabled = true;
  registerFaceButton.disabled = true;

  registrationStatus.textContent = faceRecognitionReady
    ? "Enciende la cámara para registrar otra muestra."
    : "Modelos faciales no disponibles.";
}

async function resetTracking() {
  const response = await fetch(TRACKING_RESET_URL, { method: "POST" });
  if (!response.ok) {
    throw new Error(`No se pudo reiniciar tracking (${response.status})`);
  }
}

async function refreshFaceRegistry() {
  try {
    const response = await fetch(FACE_LIST_URL);
    if (!response.ok) throw new Error(`API error ${response.status}`);

    const result = await response.json();
    faceRecognitionReady = Boolean(result.ready);
    renderRegisteredIdentities(result.identities ?? []);

    if (!faceRecognitionReady) {
      registerFaceButton.disabled = true;
      registrationStatus.textContent =
        "Faltan los modelos YuNet/SFace. Descárgalos y reinicia el backend.";
    } else if (!stream) {
      registrationStatus.textContent = "Enciende la cámara para registrar una identidad.";
    }
  } catch (error) {
    console.error(error);
    faceRecognitionReady = false;
    registerFaceButton.disabled = true;
    registrationStatus.textContent = "No se pudo consultar el registro facial.";
  }
}

function renderRegisteredIdentities(identities) {
  registeredIdentities.replaceChildren();

  if (identities.length === 0) {
    const empty = document.createElement("span");
    empty.className = "identity-empty";
    empty.textContent = "Aún no hay identidades registradas.";
    registeredIdentities.appendChild(empty);
    return;
  }

  for (const identity of identities) {
    const item = document.createElement("div");
    item.className = "registered-identity";

    const name = document.createElement("strong");
    name.textContent = identity.name;

    const samples = document.createElement("span");
    samples.textContent = `${identity.sample_count} muestra${identity.sample_count === 1 ? "" : "s"}`;

    item.append(name, samples);
    registeredIdentities.appendChild(item);
  }
}

async function registerCurrentFace() {
  const name = identityName.value.trim();

  if (!stream) {
    registrationStatus.textContent = "Primero enciende la cámara.";
    return;
  }

  if (name.length < 2) {
    registrationStatus.textContent = "Ingresa un nombre válido.";
    identityName.focus();
    return;
  }

  registerFaceButton.disabled = true;
  registrationStatus.textContent = "Capturando y generando embedding facial...";

  try {
    const blob = await captureFrameBlob();
    const formData = new FormData();
    formData.append("name", name);
    formData.append("file", blob, "face-registration.jpg");

    const response = await fetch(FACE_REGISTER_URL, {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || `API error ${response.status}`);
    }

    const result = await response.json();
    registrationStatus.textContent = `${result.name}: muestra ${result.sample_count} registrada.`;
    await refreshFaceRegistry();
  } catch (error) {
    console.error(error);
    registrationStatus.textContent = error.message;
  } finally {
    registerFaceButton.disabled = !stream || !faceRecognitionReady;
  }
}

async function runDetection() {
  if (!stream || requestInFlight || video.readyState < 2) return;

  requestInFlight = true;

  try {
    const blob = await captureFrameBlob();
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
    renderTrackedPeople(result.tracks ?? []);
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

async function refreshPresenceHistory() {
  try {
    const response = await fetch(`${PRESENCE_HISTORY_URL}?session_limit=20&event_limit=40`);
    if (!response.ok) throw new Error(`API error ${response.status}`);

    const result = await response.json();
    renderPresenceHistory(result.sessions ?? []);
  } catch (error) {
    console.error(error);
    historyCount.textContent = "-";
    presenceHistory.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "tracks-empty";
    empty.textContent = "No se pudo cargar el historial.";
    presenceHistory.appendChild(empty);
  }
}

function renderPresenceHistory(sessions) {
  historyCount.textContent = String(sessions.length);
  presenceHistory.replaceChildren();

  if (sessions.length === 0) {
    const empty = document.createElement("p");
    empty.className = "tracks-empty";
    empty.textContent = "Sin sesiones registradas.";
    presenceHistory.appendChild(empty);
    return;
  }

  for (const session of sessions) {
    const card = document.createElement("article");
    card.className = `history-card history-card--${session.status}`;

    const heading = document.createElement("div");
    heading.className = "history-heading";

    const name = document.createElement("strong");
    name.textContent = session.identity_name;

    const state = document.createElement("span");
    state.className = `history-status history-status--${session.status}`;
    state.textContent = session.status === "active" ? "Activa" : "Cerrada";

    heading.append(name, state);

    const details = document.createElement("div");
    details.className = "history-details";
    details.append(
      createTrackDetail("Entrada", formatClock(session.started_at)),
      createTrackDetail(
        "Salida",
        session.status === "active" ? "Ahora" : formatClock(session.ended_at)
      ),
      createTrackDetail("Duración", formatDuration(session.duration_seconds)),
      createTrackDetail("Track", session.tracker_id == null ? "-" : `ID ${session.tracker_id}`)
    );

    card.append(heading, details);
    presenceHistory.appendChild(card);
  }
}

function renderTrackedPeople(trackStates) {
  const statusOrder = { visible: 0, lost: 1, out: 2 };
  const tracks = [...trackStates].sort((a, b) => {
    const statusDiff = (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9);
    if (statusDiff !== 0) return statusDiff;
    return a.tracker_id - b.tracker_id;
  });

  const activeCount = tracks.filter((track) => track.status !== "out").length;
  activeTrackCount.textContent = String(activeCount);
  activeTracks.replaceChildren();

  if (tracks.length === 0) {
    const empty = document.createElement("p");
    empty.className = "tracks-empty";
    empty.textContent = "Sin personas rastreadas.";
    activeTracks.appendChild(empty);
    return;
  }

  for (const track of tracks) {
    const card = document.createElement("article");
    card.className = `track-card track-card--${track.status}`;

    const id = document.createElement("span");
    id.className = "track-id";
    id.textContent = String(track.tracker_id);

    const content = document.createElement("div");
    content.className = "track-content";

    const heading = document.createElement("div");
    heading.className = "track-heading";

    const name = document.createElement("strong");
    name.textContent = track.identity_status === "confirmed"
      ? track.identity_name
      : `Persona ${track.tracker_id}`;

    const state = document.createElement("span");
    state.className = `track-status track-status--${track.status}`;
    state.textContent = getStatusLabel(track.status);

    heading.append(name, state);

    const identityLine = document.createElement("p");
    identityLine.className = `identity-state identity-state--${track.identity_status ?? "unknown"}`;
    identityLine.textContent = getIdentityLabel(track);

    const details = document.createElement("div");
    details.className = "track-details";

    details.append(
      createTrackDetail("Track", formatDuration(track.session_seconds)),
      createTrackDetail("Detección", `${(track.confidence * 100).toFixed(0)}%`),
      createTrackDetail(
        "Presencia",
        track.presence_session_id ? `Sesión #${track.presence_session_id}` : "-"
      ),
      createTrackDetail("Entrada", formatClock(track.presence_started_at ?? track.first_seen_at))
    );

    content.append(heading, identityLine, details);
    card.append(id, content);
    activeTracks.appendChild(card);
  }
}

function getIdentityLabel(track) {
  if (track.identity_status === "confirmed" && track.identity_name) {
    const score = Number(track.identity_score);
    return Number.isFinite(score)
      ? `Identidad confirmada · similitud ${score.toFixed(3)}`
      : "Identidad confirmada";
  }

  if (track.identity_status === "candidate") {
    return "Verificando identidad...";
  }

  return "Sin identificar";
}

function createTrackDetail(label, value) {
  const item = document.createElement("div");
  item.className = "track-detail";

  const key = document.createElement("span");
  key.textContent = label;

  const data = document.createElement("strong");
  data.textContent = value;

  item.append(key, data);
  return item;
}

function getStatusLabel(trackStatus) {
  if (trackStatus === "lost") return "Perdido";
  if (trackStatus === "out") return "Fuera de escena";
  return "Visible";
}

function formatDuration(value) {
  const totalSeconds = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
  }

  return `${pad(minutes)}:${pad(seconds)}`;
}

function formatClock(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function formatLastSeen(track) {
  if (track.detected_now) return "Ahora";

  const seconds = Math.max(0, Number(track.last_seen_seconds_ago) || 0);
  if (seconds < 1) return "Hace <1 s";
  return `Hace ${seconds.toFixed(1)} s`;
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function drawDetections(result) {
  clearOverlay();

  const scaleX = overlay.width / result.image_width;
  const scaleY = overlay.height / result.image_height;
  const trackMap = new Map((result.tracks ?? []).map((track) => [track.tracker_id, track]));

  ctx.lineWidth = 3;
  ctx.strokeStyle = "#7cfc8a";
  ctx.fillStyle = "#7cfc8a";
  ctx.font = "600 16px system-ui";

  for (const detection of result.detections) {
    const [x1, y1, x2, y2] = detection.box;
    const width = (x2 - x1) * scaleX;
    const height = (y2 - y1) * scaleY;
    const x = overlay.width - x2 * scaleX;
    const y = y1 * scaleY;

    ctx.strokeRect(x, y, width, height);

    const idLabel = detection.tracker_id ?? "?";
    const track = trackMap.get(detection.tracker_id);
    const label = track?.identity_status === "confirmed" && track.identity_name
      ? `${track.identity_name} · ID ${idLabel}`
      : `ID ${idLabel} · ${(detection.confidence * 100).toFixed(0)}%`;

    const textWidth = ctx.measureText(label).width;
    const labelY = Math.max(24, y);

    ctx.fillRect(x, labelY - 24, textWidth + 14, 24);
    ctx.fillStyle = "#07110a";
    ctx.fillText(label, x + 7, labelY - 7);
    ctx.fillStyle = "#7cfc8a";
  }
}

async function captureFrameBlob() {
  if (!stream || video.readyState < 2) {
    throw new Error("La cámara todavía no está lista.");
  }

  captureCanvas.width = video.videoWidth;
  captureCanvas.height = video.videoHeight;
  captureContext.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
  return canvasToBlob(captureCanvas, "image/jpeg", 0.82);
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
registerFaceButton.addEventListener("click", registerCurrentFace);
identityName.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !registerFaceButton.disabled) {
    void registerCurrentFace();
  }
});
window.addEventListener("resize", resizeCanvases);
window.addEventListener("beforeunload", stopCamera);

window.setInterval(refreshPresenceHistory, HISTORY_REFRESH_MS);
void refreshFaceRegistry();
void refreshPresenceHistory();

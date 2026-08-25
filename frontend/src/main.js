import "./styles.css";

const API_BASE_URL = "http://localhost:8000";
const DETECTION_URL = `${API_BASE_URL}/api/vision/detect`;
const TRACKING_RESET_URL = `${API_BASE_URL}/api/vision/tracking/reset`;
const FACE_LIST_URL = `${API_BASE_URL}/api/vision/faces`;
const FACE_REGISTER_URL = `${API_BASE_URL}/api/vision/faces/register`;
const PRESENCE_HISTORY_URL = `${API_BASE_URL}/api/presence/history`;
const ZONES_URL = `${API_BASE_URL}/api/zones`;
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
const zoneName = document.querySelector("#zoneName");
const startZoneButton = document.querySelector("#startZoneButton");
const saveZoneButton = document.querySelector("#saveZoneButton");
const cancelZoneButton = document.querySelector("#cancelZoneButton");
const zoneStatus = document.querySelector("#zoneStatus");
const zoneList = document.querySelector("#zoneList");
const zoneCount = document.querySelector("#zoneCount");

let stream = null;
let loopId = null;
let requestInFlight = false;
let faceRecognitionReady = false;
let lastDetectionResult = null;
let currentZones = [];
let zoneEditMode = false;
let zoneDraftPoints = [];

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
    await Promise.all([refreshPresenceHistory(), refreshZones()]);

    resizeCanvases();
    renderTrackedPeople([]);
    renderOverlay();
    status.textContent = "Detectando";
    status.classList.add("status--active");
    startButton.disabled = true;
    stopButton.disabled = false;
    registerFaceButton.disabled = !faceRecognitionReady;
    startZoneButton.disabled = false;

    if (faceRecognitionReady) {
      registrationStatus.textContent = "Escribe un nombre y mira de frente a la cámara.";
    }
    zoneStatus.textContent = "Escribe un nombre y pulsa Dibujar zona.";

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

  cancelZoneDrawing(false);
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  video.srcObject = null;
  requestInFlight = false;
  lastDetectionResult = null;

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
  startZoneButton.disabled = true;
  saveZoneButton.disabled = true;
  cancelZoneButton.disabled = true;

  registrationStatus.textContent = faceRecognitionReady
    ? "Enciende la cámara para registrar otra muestra."
    : "Modelos faciales no disponibles.";
  zoneStatus.textContent = "Enciende la cámara para configurar zonas.";
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

async function refreshZones() {
  try {
    const response = await fetch(ZONES_URL);
    if (!response.ok) throw new Error(`API error ${response.status}`);
    const result = await response.json();
    currentZones = result.zones ?? [];
    renderZoneList();
    renderOverlay();
  } catch (error) {
    console.error(error);
    zoneCount.textContent = "-";
    zoneStatus.textContent = "No se pudieron cargar las zonas.";
  }
}

function renderZoneList() {
  zoneCount.textContent = String(currentZones.length);
  zoneList.replaceChildren();

  if (currentZones.length === 0) {
    const empty = document.createElement("span");
    empty.className = "identity-empty";
    empty.textContent = "Aún no hay zonas configuradas.";
    zoneList.appendChild(empty);
    return;
  }

  for (const zone of currentZones) {
    const item = document.createElement("div");
    item.className = "zone-item";

    const info = document.createElement("div");
    info.className = "zone-item__info";

    const name = document.createElement("strong");
    name.textContent = zone.name;

    const meta = document.createElement("span");
    meta.textContent = `${zone.polygon.length} puntos`;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Quitar";
    remove.addEventListener("click", () => void disableZone(zone));

    info.append(name, meta);
    item.append(info, remove);
    zoneList.appendChild(item);
  }
}

function startZoneDrawing() {
  if (!stream) {
    zoneStatus.textContent = "Primero enciende la cámara.";
    return;
  }

  if (zoneName.value.trim().length < 2) {
    zoneStatus.textContent = "Escribe el nombre de la zona antes de dibujar.";
    zoneName.focus();
    return;
  }

  zoneEditMode = true;
  zoneDraftPoints = [];
  overlay.classList.add("overlay--editing");
  startZoneButton.disabled = true;
  cancelZoneButton.disabled = false;
  updateZoneSaveState();
  zoneStatus.textContent = "Haz clic sobre la cámara para marcar al menos 3 puntos.";
  renderOverlay();
}

function cancelZoneDrawing(showMessage = true) {
  zoneEditMode = false;
  zoneDraftPoints = [];
  overlay.classList.remove("overlay--editing");
  startZoneButton.disabled = !stream;
  saveZoneButton.disabled = true;
  cancelZoneButton.disabled = true;
  if (showMessage) {
    zoneStatus.textContent = stream
      ? "Dibujo cancelado. Puedes crear otra zona."
      : "Enciende la cámara para configurar zonas.";
  }
  renderOverlay();
}

function updateZoneSaveState() {
  saveZoneButton.disabled = !zoneEditMode || zoneDraftPoints.length < 3 || zoneName.value.trim().length < 2;
}

function addZonePoint(event) {
  if (!zoneEditMode || !stream || overlay.width === 0 || overlay.height === 0) return;

  const rect = overlay.getBoundingClientRect();
  const displayX = (event.clientX - rect.left) / rect.width;
  const displayY = (event.clientY - rect.top) / rect.height;

  if (displayX < 0 || displayX > 1 || displayY < 0 || displayY > 1) return;

  const sourceX = 1 - displayX;
  zoneDraftPoints.push([
    Number(sourceX.toFixed(6)),
    Number(displayY.toFixed(6))
  ]);

  updateZoneSaveState();
  zoneStatus.textContent = `${zoneDraftPoints.length} punto${zoneDraftPoints.length === 1 ? "" : "s"} marcado${zoneDraftPoints.length === 1 ? "" : "s"}.`;
  renderOverlay();
}

async function saveZone() {
  const name = zoneName.value.trim();
  if (name.length < 2 || zoneDraftPoints.length < 3) return;

  saveZoneButton.disabled = true;
  zoneStatus.textContent = "Guardando zona...";

  try {
    const response = await fetch(ZONES_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, polygon: zoneDraftPoints })
    });

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || `API error ${response.status}`);
    }

    cancelZoneDrawing(false);
    zoneName.value = "";
    await refreshZones();
    zoneStatus.textContent = `Zona ${name} guardada.`;
  } catch (error) {
    console.error(error);
    zoneStatus.textContent = error.message;
    updateZoneSaveState();
  }
}

async function disableZone(zone) {
  try {
    const response = await fetch(`${ZONES_URL}/${encodeURIComponent(zone.id)}/delete`, {
      method: "POST"
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || `API error ${response.status}`);
    }
    await refreshZones();
    zoneStatus.textContent = `Zona ${zone.name} desactivada.`;
  } catch (error) {
    console.error(error);
    zoneStatus.textContent = error.message;
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
    lastDetectionResult = result;
    renderOverlay();
    renderTrackedPeople(result.tracks ?? []);
    peopleCount.textContent = String(result.detections.length);
    inferenceMs.textContent = String(result.inference_ms);
    status.textContent = "Detectando";
  } catch (error) {
    console.error(error);
    status.textContent = error.message;
    lastDetectionResult = null;
    renderOverlay();
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
      createTrackDetail("Entrada", formatClock(track.presence_started_at ?? track.first_seen_at)),
      createTrackDetail("Zona", track.current_zone_name ?? "Sin zona"),
      createTrackDetail(
        "Tiempo zona",
        track.current_zone_name && track.zone_seconds != null
          ? formatDuration(track.zone_seconds)
          : "-"
      )
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

function pad(value) {
  return String(value).padStart(2, "0");
}

function renderOverlay() {
  clearOverlay();
  drawZones();
  if (lastDetectionResult) {
    drawDetectionBoxes(lastDetectionResult);
  }
  drawZoneDraft();
}

function drawZones() {
  if (!overlay.width || !overlay.height) return;

  for (const zone of currentZones) {
    drawPolygon(zone.polygon, {
      fill: "rgba(98, 180, 255, 0.10)",
      stroke: "rgba(98, 180, 255, 0.85)",
      lineWidth: 2,
      close: true
    });

    const first = zone.polygon[0];
    if (!first) continue;
    const [x, y] = normalizedToDisplay(first);
    ctx.save();
    ctx.font = "600 14px system-ui";
    const labelWidth = ctx.measureText(zone.name).width;
    ctx.fillStyle = "rgba(8, 18, 29, 0.86)";
    ctx.fillRect(x, Math.max(0, y - 23), labelWidth + 14, 22);
    ctx.fillStyle = "#d7ecff";
    ctx.fillText(zone.name, x + 7, Math.max(15, y - 7));
    ctx.restore();
  }
}

function drawZoneDraft() {
  if (!zoneEditMode || zoneDraftPoints.length === 0) return;

  drawPolygon(zoneDraftPoints, {
    fill: zoneDraftPoints.length >= 3 ? "rgba(124, 252, 138, 0.12)" : null,
    stroke: "#7cfc8a",
    lineWidth: 3,
    close: zoneDraftPoints.length >= 3
  });

  ctx.save();
  for (const point of zoneDraftPoints) {
    const [x, y] = normalizedToDisplay(point);
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fillStyle = "#7cfc8a";
    ctx.fill();
    ctx.strokeStyle = "#07110a";
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  ctx.restore();
}

function drawPolygon(points, options) {
  if (!points || points.length === 0) return;

  ctx.save();
  ctx.beginPath();
  points.forEach((point, index) => {
    const [x, y] = normalizedToDisplay(point);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  if (options.close) ctx.closePath();
  if (options.fill) {
    ctx.fillStyle = options.fill;
    ctx.fill();
  }
  ctx.strokeStyle = options.stroke;
  ctx.lineWidth = options.lineWidth;
  ctx.stroke();
  ctx.restore();
}

function normalizedToDisplay(point) {
  const sourceX = Number(point[0]);
  const sourceY = Number(point[1]);
  return [
    overlay.width * (1 - sourceX),
    overlay.height * sourceY
  ];
}

function drawDetectionBoxes(result) {
  const scaleX = overlay.width / result.image_width;
  const scaleY = overlay.height / result.image_height;
  const trackMap = new Map((result.tracks ?? []).map((track) => [track.tracker_id, track]));

  ctx.save();
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

    ctx.fillStyle = "#7cfc8a";
    ctx.fillRect(x, labelY - 24, textWidth + 14, 24);
    ctx.fillStyle = "#07110a";
    ctx.fillText(label, x + 7, labelY - 7);

    if (track?.current_zone_name) {
      const zoneLabel = track.current_zone_name;
      const zoneWidth = ctx.measureText(zoneLabel).width;
      ctx.fillStyle = "rgba(8, 18, 29, 0.88)";
      ctx.fillRect(x, labelY, zoneWidth + 14, 22);
      ctx.fillStyle = "#d7ecff";
      ctx.fillText(zoneLabel, x + 7, labelY + 16);
    }

    const footX = x + width / 2;
    const footY = y + height;
    ctx.beginPath();
    ctx.arc(footX, footY, 5, 0, Math.PI * 2);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.strokeStyle = "#07110a";
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  ctx.restore();
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
  renderOverlay();
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
startZoneButton.addEventListener("click", startZoneDrawing);
saveZoneButton.addEventListener("click", saveZone);
cancelZoneButton.addEventListener("click", () => cancelZoneDrawing(true));
overlay.addEventListener("click", addZonePoint);
zoneName.addEventListener("input", updateZoneSaveState);
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
void refreshZones();

import "./dashboard.css";

const API_BASE_URL = "http://localhost:8000";
const PRESENCE_HISTORY_URL = `${API_BASE_URL}/api/presence/history`;
const ZONE_HISTORY_URL = `${API_BASE_URL}/api/zones/history`;
const INTERACTION_HISTORY_URL = `${API_BASE_URL}/api/interactions/history`;
const REFRESH_MS = 3000;

const historyDate = document.querySelector("#historyDate");
const employeeFilter = document.querySelector("#employeeFilter");
const historyRefreshStatus = document.querySelector("#historyRefreshStatus");
const presenceSessionCount = document.querySelector("#presenceSessionCount");
const zoneSessionCount = document.querySelector("#zoneSessionCount");
const interactionSessionCount = document.querySelector("#interactionSessionCount");
const eventCount = document.querySelector("#eventCount");
const presenceTableBody = document.querySelector("#presenceTableBody");
const zoneTableBody = document.querySelector("#zoneTableBody");
const interactionTableBody = document.querySelector("#interactionTableBody");
const timelineList = document.querySelector("#timelineList");
const historyError = document.querySelector("#historyError");

let presenceData = { sessions: [], events: [] };
let zoneData = { sessions: [], events: [] };
let interactionData = { sessions: [], events: [] };
let refreshInFlight = false;

historyDate.value = localDateValue(new Date());
historyDate.addEventListener("change", renderHistory);
employeeFilter.addEventListener("change", renderHistory);

async function refreshHistory() {
  if (refreshInFlight) return;
  refreshInFlight = true;

  try {
    const [presenceResponse, zoneResponse, interactionResponse] = await Promise.all([
      fetch(`${PRESENCE_HISTORY_URL}?session_limit=200&event_limit=500`),
      fetch(`${ZONE_HISTORY_URL}?session_limit=300&event_limit=500`),
      fetch(`${INTERACTION_HISTORY_URL}?session_limit=300&event_limit=500`)
    ]);

    if (!presenceResponse.ok) {
      throw new Error(`Historial de presencia: API ${presenceResponse.status}`);
    }
    if (!zoneResponse.ok) {
      throw new Error(`Historial de zonas: API ${zoneResponse.status}`);
    }
    if (!interactionResponse.ok) {
      throw new Error(`Historial de interacciones: API ${interactionResponse.status}`);
    }

    [presenceData, zoneData, interactionData] = await Promise.all([
      presenceResponse.json(),
      zoneResponse.json(),
      interactionResponse.json()
    ]);

    refreshEmployeeFilter();
    renderHistory();
    historyError.hidden = true;
    historyRefreshStatus.textContent = `Actualizado ${formatClock(new Date())}`;
  } catch (error) {
    console.error(error);
    historyError.hidden = false;
    historyError.textContent = error.message || "No se pudo actualizar el historial.";
    historyRefreshStatus.textContent = "Sin conexión";
  } finally {
    refreshInFlight = false;
  }
}

function refreshEmployeeFilter() {
  const selected = employeeFilter.value;
  const identities = new Map();

  for (const session of presenceData.sessions ?? []) {
    identities.set(String(session.identity_id), session.identity_name);
  }
  for (const session of zoneData.sessions ?? []) {
    identities.set(String(session.identity_id), session.identity_name);
  }
  for (const session of interactionData.sessions ?? []) {
    identities.set(String(session.identity_id), session.identity_name);
  }

  const sorted = [...identities.entries()].sort((a, b) =>
    a[1].localeCompare(b[1], "es", { sensitivity: "base" })
  );

  employeeFilter.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "Todos";
  employeeFilter.appendChild(all);

  for (const [identityId, name] of sorted) {
    const option = document.createElement("option");
    option.value = identityId;
    option.textContent = name;
    employeeFilter.appendChild(option);
  }

  if ([...employeeFilter.options].some((option) => option.value === selected)) {
    employeeFilter.value = selected;
  }
}

function renderHistory() {
  const dateValue = historyDate.value;
  const identityId = employeeFilter.value;
  const bounds = getDayBounds(dateValue);

  const presenceSessions = (presenceData.sessions ?? []).filter((session) =>
    matchesSession(session, identityId, bounds, "started_at", "ended_at", "last_seen_at")
  );
  const zoneSessions = (zoneData.sessions ?? []).filter((session) =>
    matchesSession(session, identityId, bounds, "entered_at", "exited_at", "last_seen_at")
  );
  const interactionSessions = (interactionData.sessions ?? []).filter((session) =>
    matchesSession(session, identityId, bounds, "started_at", "ended_at", "last_seen_at")
  );

  const presenceEvents = (presenceData.events ?? [])
    .filter((event) => matchesEvent(event, identityId, bounds))
    .map((event) => ({ ...event, source: "presence" }));
  const zoneEvents = (zoneData.events ?? [])
    .filter((event) => matchesEvent(event, identityId, bounds))
    .map((event) => ({ ...event, source: "zone" }));
  const interactionEvents = (interactionData.events ?? [])
    .filter((event) => matchesEvent(event, identityId, bounds))
    .map((event) => ({ ...event, source: "interaction" }));

  const events = [...presenceEvents, ...zoneEvents, ...interactionEvents].sort(
    (a, b) => new Date(b.occurred_at) - new Date(a.occurred_at)
  );

  renderPresenceTable(presenceSessions);
  renderZoneTable(zoneSessions);
  renderInteractionTable(interactionSessions);
  renderTimeline(events);

  presenceSessionCount.textContent = String(presenceSessions.length);
  zoneSessionCount.textContent = String(zoneSessions.length);
  interactionSessionCount.textContent = String(interactionSessions.length);
  eventCount.textContent = String(events.length);
}

function renderPresenceTable(sessions) {
  presenceTableBody.replaceChildren();

  if (sessions.length === 0) {
    appendEmptyRow(presenceTableBody, 6, "Sin sesiones de presencia para estos filtros.");
    return;
  }

  for (const session of sessions) {
    const row = document.createElement("tr");
    row.append(
      createCell(session.identity_name),
      createCell(formatDateTime(session.started_at)),
      createCell(session.status === "active" ? "Ahora" : formatDateTime(session.ended_at)),
      createCell(formatDuration(effectiveDuration(session, "started_at", "ended_at", "last_seen_at"))),
      createStatusCell(session.status),
      createCell(session.tracker_id == null ? "-" : `ID ${session.tracker_id}`)
    );
    presenceTableBody.appendChild(row);
  }
}

function renderZoneTable(sessions) {
  zoneTableBody.replaceChildren();

  if (sessions.length === 0) {
    appendEmptyRow(zoneTableBody, 6, "Sin permanencia en zonas para estos filtros.");
    return;
  }

  for (const session of sessions) {
    const row = document.createElement("tr");
    row.append(
      createCell(session.identity_name),
      createCell(session.zone_name),
      createCell(formatDateTime(session.entered_at)),
      createCell(session.status === "active" ? "Ahora" : formatDateTime(session.exited_at)),
      createCell(formatDuration(effectiveDuration(session, "entered_at", "exited_at", "last_seen_at"))),
      createStatusCell(session.status)
    );
    zoneTableBody.appendChild(row);
  }
}

function renderInteractionTable(sessions) {
  interactionTableBody.replaceChildren();

  if (sessions.length === 0) {
    appendEmptyRow(interactionTableBody, 7, "Sin interacciones confirmadas para estos filtros.");
    return;
  }

  for (const session of sessions) {
    const row = document.createElement("tr");
    const other = session.other_identity_name
      ?? (session.other_tracker_id == null ? "Persona" : `Persona ID ${session.other_tracker_id}`);
    row.append(
      createCell(session.identity_name),
      createCell(other),
      createCell(session.zone_name ?? "Sin zona"),
      createCell(formatDateTime(session.started_at)),
      createCell(session.status === "active" ? "Ahora" : formatDateTime(session.ended_at)),
      createCell(formatDuration(effectiveDuration(session, "started_at", "ended_at", "last_seen_at"))),
      createStatusCell(session.status)
    );
    interactionTableBody.appendChild(row);
  }
}

function renderTimeline(events) {
  timelineList.replaceChildren();

  if (events.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Sin eventos para los filtros seleccionados.";
    timelineList.appendChild(empty);
    return;
  }

  for (const event of events) {
    const item = document.createElement("div");
    item.className = "timeline-item";

    const time = document.createElement("span");
    time.className = "timeline-time";
    time.textContent = formatClock(event.occurred_at);

    const type = document.createElement("span");
    type.className = "timeline-type";
    type.textContent = eventLabel(event.event_type);

    const description = document.createElement("span");
    description.className = "timeline-description";
    if (event.source === "zone") {
      description.textContent = `${event.identity_name} · ${event.zone_name}`;
    } else if (event.source === "interaction") {
      const other = event.other_identity_name
        ?? (event.other_tracker_id == null ? "persona" : `Persona ID ${event.other_tracker_id}`);
      const zone = event.zone_name ? ` · ${event.zone_name}` : "";
      description.textContent = `${event.identity_name} ↔ ${other}${zone}`;
    } else {
      description.textContent = `${event.identity_name}${event.tracker_id == null ? "" : ` · ID ${event.tracker_id}`}`;
    }

    item.append(time, type, description);
    timelineList.appendChild(item);
  }
}

function matchesSession(session, identityId, bounds, startKey, endKey, fallbackEndKey) {
  if (identityId && String(session.identity_id) !== identityId) return false;

  const start = new Date(session[startKey]);
  const end = session.status === "active"
    ? new Date()
    : new Date(session[endKey] ?? session[fallbackEndKey]);

  return start < bounds.end && end >= bounds.start;
}

function matchesEvent(event, identityId, bounds) {
  if (identityId && String(event.identity_id) !== identityId) return false;
  const occurred = new Date(event.occurred_at);
  return occurred >= bounds.start && occurred < bounds.end;
}

function effectiveDuration(session, startKey, endKey, fallbackEndKey) {
  const start = new Date(session[startKey]);
  const end = session.status === "active"
    ? new Date()
    : new Date(session[endKey] ?? session[fallbackEndKey]);
  return Math.max(0, (end - start) / 1000);
}

function createCell(value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  return cell;
}

function createStatusCell(status) {
  const cell = document.createElement("td");
  const pill = document.createElement("span");
  pill.className = `status-pill${status === "active" ? " status-pill--active" : ""}`;
  pill.textContent = status === "active" ? "Activa" : "Cerrada";
  cell.appendChild(pill);
  return cell;
}

function appendEmptyRow(body, columns, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.textContent = message;
  cell.style.textAlign = "center";
  cell.style.color = "#788392";
  row.appendChild(cell);
  body.appendChild(row);
}

function eventLabel(type) {
  const labels = {
    ENTER: "Entrada",
    IDENTIFIED: "Identificado",
    LOST: "Perdido",
    RETURNED: "Retorno",
    EXIT: "Salida",
    ENTER_ZONE: "Entrada zona",
    EXIT_ZONE: "Salida zona",
    INTERACTION_START: "Interacción inicia",
    INTERACTION_END: "Interacción termina"
  };
  return labels[type] ?? type;
}

function getDayBounds(value) {
  const [year, month, day] = value.split("-").map(Number);
  return {
    start: new Date(year, month - 1, day, 0, 0, 0, 0),
    end: new Date(year, month - 1, day + 1, 0, 0, 0, 0)
  };
}

function localDateValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString([], {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function formatClock(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function formatDuration(value) {
  const totalSeconds = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

function pad(value) {
  return String(value).padStart(2, "0");
}

window.setInterval(refreshHistory, REFRESH_MS);
void refreshHistory();

import "./dashboard.css";

const API_BASE_URL = "http://localhost:8000";
const PRESENCE_HISTORY_URL = `${API_BASE_URL}/api/presence/history`;
const ZONE_HISTORY_URL = `${API_BASE_URL}/api/zones/history`;
const INTERACTION_HISTORY_URL = `${API_BASE_URL}/api/interactions/history`;
const OPERATIONAL_STATUS_URL = `${API_BASE_URL}/api/operations/status`;
const OPERATIONAL_HISTORY_URL = `${API_BASE_URL}/api/operations/history`;
const BEHAVIOR_STATUS_URL = `${API_BASE_URL}/api/behaviors/status`;
const BEHAVIOR_HISTORY_URL = `${API_BASE_URL}/api/behaviors/history`;
const REFRESH_MS = 2000;

const summaryDate = document.querySelector("#summaryDate");
const refreshStatus = document.querySelector("#refreshStatus");
const moduleStatus = document.querySelector("#moduleStatus");
const counterStatus = document.querySelector("#counterStatus");
const moduleIncidentCount = document.querySelector("#moduleIncidentCount");
const activePhoneSignals = document.querySelector("#activePhoneSignals");
const phoneIncidentCount = document.querySelector("#phoneIncidentCount");
const activeEmployees = document.querySelector("#activeEmployees");
const detectedEmployees = document.querySelector("#detectedEmployees");
const totalPresence = document.querySelector("#totalPresence");
const totalZoneTime = document.querySelector("#totalZoneTime");
const totalInteractions = document.querySelector("#totalInteractions");
const totalInteractionTime = document.querySelector("#totalInteractionTime");
const employeeCount = document.querySelector("#employeeCount");
const employeeGrid = document.querySelector("#employeeGrid");
const summaryError = document.querySelector("#summaryError");

let refreshInFlight = false;

summaryDate.value = localDateValue(new Date());
summaryDate.addEventListener("change", () => void refreshSummary());

async function refreshSummary() {
  if (refreshInFlight) return;
  refreshInFlight = true;

  try {
    const [
      presenceResponse,
      zoneResponse,
      interactionResponse,
      operationalStatusResponse,
      operationalHistoryResponse,
      behaviorStatusResponse,
      behaviorHistoryResponse
    ] = await Promise.all([
      fetch(`${PRESENCE_HISTORY_URL}?session_limit=200&event_limit=1`),
      fetch(`${ZONE_HISTORY_URL}?session_limit=300&event_limit=1`),
      fetch(`${INTERACTION_HISTORY_URL}?session_limit=300&event_limit=1`),
      fetch(OPERATIONAL_STATUS_URL),
      fetch(`${OPERATIONAL_HISTORY_URL}?incident_limit=500&event_limit=1`),
      fetch(BEHAVIOR_STATUS_URL),
      fetch(`${BEHAVIOR_HISTORY_URL}?incident_limit=500&event_limit=1`)
    ]);

    const responses = [
      [presenceResponse, "Historial de presencia"],
      [zoneResponse, "Historial de zonas"],
      [interactionResponse, "Historial de interacciones"],
      [operationalStatusResponse, "Estado operativo"],
      [operationalHistoryResponse, "Historial operativo"],
      [behaviorStatusResponse, "Estado de comportamientos"],
      [behaviorHistoryResponse, "Historial de comportamientos"]
    ];

    for (const [response, label] of responses) {
      if (!response.ok) throw new Error(`${label}: API ${response.status}`);
    }

    const [
      presence,
      zones,
      interactions,
      operationalStatusData,
      operationalHistory,
      behaviorStatusData,
      behaviorHistory
    ] = await Promise.all([
      presenceResponse.json(),
      zoneResponse.json(),
      interactionResponse.json(),
      operationalStatusResponse.json(),
      operationalHistoryResponse.json(),
      behaviorStatusResponse.json(),
      behaviorHistoryResponse.json()
    ]);

    const dateValue = summaryDate.value;
    const behaviorIncidents = filterIncidentsForDate(
      behaviorHistory.incidents ?? [],
      dateValue
    );

    const employees = aggregateEmployees(
      presence.sessions ?? [],
      zones.sessions ?? [],
      interactions.sessions ?? [],
      behaviorIncidents,
      isToday(dateValue) ? behaviorStatusData.signals ?? [] : [],
      operationalStatusData.counter_zone_names ?? [],
      dateValue
    );

    const operationalIncidents = filterIncidentsForDate(
      operationalHistory.incidents ?? [],
      dateValue
    );

    renderOperationalStatus(operationalStatusData, operationalIncidents.length);
    renderBehaviorStatus(
      behaviorStatusData.signals ?? [],
      behaviorIncidents
    );
    renderSummary(employees);

    summaryError.hidden = true;
    refreshStatus.textContent = `Actualizado ${formatClock(new Date())}`;
  } catch (error) {
    console.error(error);
    summaryError.hidden = false;
    summaryError.textContent = error.message || "No se pudo actualizar el resumen.";
    refreshStatus.textContent = "Sin conexión";
  } finally {
    refreshInFlight = false;
  }
}

function aggregateEmployees(
  presenceSessions,
  zoneSessions,
  interactionSessions,
  behaviorIncidents,
  liveBehaviorSignals,
  counterZoneNames,
  dateValue
) {
  const bounds = getDayBounds(dateValue);
  const now = new Date();
  const employees = new Map();
  const counterKeys = new Set(
    counterZoneNames.map((name) => String(name).trim().toLocaleLowerCase("es"))
  );

  for (const session of presenceSessions) {
    const start = new Date(session.started_at);
    const rawEnd = session.status === "active"
      ? now
      : new Date(session.ended_at ?? session.last_seen_at);

    if (!datesOverlap(start, rawEnd, bounds.start, bounds.end)) continue;

    const item = getEmployee(employees, session.identity_id, session.identity_name);
    const clippedStart = new Date(Math.max(start.getTime(), bounds.start.getTime()));
    const clippedEnd = new Date(Math.min(rawEnd.getTime(), bounds.end.getTime()));
    const seconds = Math.max(0, (clippedEnd - clippedStart) / 1000);

    item.totalPresenceSeconds += seconds;
    item.sessionCount += 1;

    if (!item.firstSeen || clippedStart < item.firstSeen) item.firstSeen = clippedStart;
    if (!item.lastSeen || clippedEnd > item.lastSeen) item.lastSeen = clippedEnd;

    if (session.status === "active") {
      item.status = "active";
      item.trackerId = session.tracker_id;
      item.activeSessionId = session.id;
      item.activeStartedAt = new Date(session.started_at);
      item.identityScore = session.identity_score;
    } else if (item.identityScore == null && session.identity_score != null) {
      item.identityScore = session.identity_score;
    }
  }

  for (const session of zoneSessions) {
    const start = new Date(session.entered_at);
    const rawEnd = session.status === "active"
      ? now
      : new Date(session.exited_at ?? session.last_seen_at);

    if (!datesOverlap(start, rawEnd, bounds.start, bounds.end)) continue;

    const item = employees.get(String(session.identity_id));
    if (!item) continue;

    const clippedStart = new Date(Math.max(start.getTime(), bounds.start.getTime()));
    const clippedEnd = new Date(Math.min(rawEnd.getTime(), bounds.end.getTime()));
    const seconds = Math.max(0, (clippedEnd - clippedStart) / 1000);
    const key = String(session.zone_id);
    const current = item.zones.get(key) ?? {
      zoneId: key,
      zoneName: session.zone_name,
      seconds: 0
    };

    current.seconds += seconds;
    item.zones.set(key, current);
    item.totalZoneSeconds += seconds;

    const zoneNameKey = String(session.zone_name ?? "")
      .trim()
      .toLocaleLowerCase("es");

    if (counterKeys.has(zoneNameKey)) {
      item.counterSeconds += seconds;
      if (session.status === "active") item.atCounter = true;
    }

    if (session.status === "active") {
      item.currentZoneId = key;
      item.currentZoneName = session.zone_name;
      item.currentZoneEnteredAt = new Date(session.entered_at);
    }
  }

  for (const session of interactionSessions) {
    const start = new Date(session.started_at);
    const rawEnd = session.status === "active"
      ? now
      : new Date(session.ended_at ?? session.last_seen_at);

    if (!datesOverlap(start, rawEnd, bounds.start, bounds.end)) continue;

    const item = employees.get(String(session.identity_id));
    if (!item) continue;

    const clippedStart = new Date(Math.max(start.getTime(), bounds.start.getTime()));
    const clippedEnd = new Date(Math.min(rawEnd.getTime(), bounds.end.getTime()));
    const seconds = Math.max(0, (clippedEnd - clippedStart) / 1000);

    item.interactionCount += 1;
    item.totalInteractionSeconds += seconds;
    if (session.status === "active") item.activeInteractionCount += 1;
  }

  for (const incident of behaviorIncidents) {
    if (incident.behavior_type !== "PHONE_USE_LONG") continue;
    const item = employees.get(String(incident.identity_id));
    if (!item) continue;

    const start = new Date(incident.started_at);
    const rawEnd = incident.status === "active"
      ? now
      : new Date(incident.ended_at ?? incident.last_seen_at);
    const clippedStart = new Date(Math.max(start.getTime(), bounds.start.getTime()));
    const clippedEnd = new Date(Math.min(rawEnd.getTime(), bounds.end.getTime()));

    item.phoneIncidentCount += 1;
    item.phoneIncidentSeconds += Math.max(0, (clippedEnd - clippedStart) / 1000);
  }

  for (const signal of liveBehaviorSignals) {
    if (signal.behavior_type !== "PHONE_USE_LONG") continue;
    const item = employees.get(String(signal.identity_id));
    if (!item) continue;

    item.phoneVisibleNow = Boolean(signal.phone_visible_now);
    item.phoneVisibleSeconds = Number(signal.phone_visible_seconds) || 0;
    item.phoneUseLong = Boolean(signal.confirmed);
    item.phoneSignalConfidence = Number(signal.confidence) || 0;
  }

  const result = [...employees.values()].map((item) => ({
    ...item,
    unassignedSeconds: Math.max(0, item.totalPresenceSeconds - item.totalZoneSeconds),
    zones: [...item.zones.values()].sort((a, b) => b.seconds - a.seconds)
  }));

  result.sort((a, b) => {
    if (a.status !== b.status) return a.status === "active" ? -1 : 1;
    return a.identityName.localeCompare(b.identityName, "es", { sensitivity: "base" });
  });

  return result;
}

function getEmployee(map, identityId, identityName) {
  const key = String(identityId);
  let item = map.get(key);

  if (!item) {
    item = {
      identityId: key,
      identityName,
      status: "offline",
      trackerId: null,
      activeSessionId: null,
      activeStartedAt: null,
      identityScore: null,
      firstSeen: null,
      lastSeen: null,
      sessionCount: 0,
      totalPresenceSeconds: 0,
      totalZoneSeconds: 0,
      interactionCount: 0,
      activeInteractionCount: 0,
      totalInteractionSeconds: 0,
      counterSeconds: 0,
      atCounter: false,
      phoneIncidentCount: 0,
      phoneIncidentSeconds: 0,
      phoneVisibleNow: false,
      phoneVisibleSeconds: 0,
      phoneUseLong: false,
      phoneSignalConfidence: 0,
      currentZoneId: null,
      currentZoneName: null,
      currentZoneEnteredAt: null,
      zones: new Map()
    };
    map.set(key, item);
  }

  return item;
}

function renderOperationalStatus(statusData, incidentCount) {
  moduleIncidentCount.textContent = String(incidentCount);

  if (!statusData.monitored) {
    moduleStatus.textContent = "Sin zonas";
  } else if (!statusData.module_armed) {
    moduleStatus.textContent = "Esperando presencia";
  } else if (statusData.module_abandoned) {
    moduleStatus.textContent = `ABANDONO ${formatDuration(statusData.module_empty_seconds)}`;
  } else if (statusData.module_empty) {
    moduleStatus.textContent = `Vacío ${formatDuration(statusData.module_empty_seconds)}`;
  } else {
    moduleStatus.textContent = "Operativo";
  }

  if ((statusData.counter_zone_names ?? []).length === 0) {
    counterStatus.textContent = "Sin configurar";
  } else if (statusData.counter_occupied) {
    const count = (statusData.employees_at_counter ?? []).length;
    counterStatus.textContent = `${count} presente${count === 1 ? "" : "s"}`;
  } else {
    counterStatus.textContent = "Sin presencia";
  }
}

function renderBehaviorStatus(signals, incidents) {
  const activeSignals = signals.filter(
    (signal) => signal.behavior_type === "PHONE_USE_LONG" && signal.phone_visible_now
  );

  const confirmedIncidents = incidents.filter(
    (incident) => incident.behavior_type === "PHONE_USE_LONG"
  );

  activePhoneSignals.textContent = String(activeSignals.length);
  phoneIncidentCount.textContent = String(confirmedIncidents.length);
}

function renderSummary(employees) {
  const active = employees.filter((employee) => employee.status === "active").length;
  const presenceSeconds = employees.reduce(
    (sum, employee) => sum + employee.totalPresenceSeconds,
    0
  );
  const zoneSeconds = employees.reduce(
    (sum, employee) => sum + employee.totalZoneSeconds,
    0
  );
  const interactionCount = employees.reduce(
    (sum, employee) => sum + employee.interactionCount,
    0
  );
  const interactionSeconds = employees.reduce(
    (sum, employee) => sum + employee.totalInteractionSeconds,
    0
  );

  activeEmployees.textContent = String(active);
  detectedEmployees.textContent = String(employees.length);
  totalPresence.textContent = formatDuration(presenceSeconds);
  totalZoneTime.textContent = formatDuration(zoneSeconds);
  totalInteractions.textContent = String(interactionCount);
  totalInteractionTime.textContent = formatDuration(interactionSeconds);
  employeeCount.textContent = String(employees.length);
  employeeGrid.replaceChildren();

  if (employees.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Todavía no hay datos para esta fecha.";
    employeeGrid.appendChild(empty);
    return;
  }

  for (const employee of employees) {
    employeeGrid.appendChild(createEmployeeCard(employee));
  }
}

function createEmployeeCard(employee) {
  const card = document.createElement("article");
  card.className = `employee-card employee-card--${employee.status}`;

  const heading = document.createElement("div");
  heading.className = "employee-heading";

  const title = document.createElement("h3");
  title.textContent = employee.identityName;

  const state = document.createElement("span");
  state.className = `employee-state employee-state--${employee.status}`;
  state.textContent = employee.status === "active" ? "EN CÁMARA" : "FUERA";
  heading.append(title, state);

  const currentZone = document.createElement("p");
  currentZone.className = "employee-current-zone";

  if (employee.status === "active") {
    const badges = [];

    if (employee.atCounter) badges.push("EN COUNTER");
    if (employee.activeInteractionCount > 0) {
      badges.push(
        `${employee.activeInteractionCount} interacción${employee.activeInteractionCount === 1 ? "" : "es"} activa${employee.activeInteractionCount === 1 ? "" : "s"}`
      );
    }
    if (employee.phoneVisibleNow) {
      badges.push(
        employee.phoneUseLong
          ? `CELULAR >10 MIN (${formatDuration(employee.phoneVisibleSeconds)})`
          : `celular visible ${formatDuration(employee.phoneVisibleSeconds)}`
      );
    }

    currentZone.textContent = `Zona actual: ${employee.currentZoneName ?? "Sin zona"}${
      badges.length ? ` · ${badges.join(" · ")}` : ""
    }`;
  } else {
    currentZone.textContent = "Sin presencia activa";
  }

  const details = document.createElement("div");
  details.className = "employee-details";
  details.append(
    createDetail("Presencia", formatDuration(employee.totalPresenceSeconds)),
    createDetail("Tiempo en zonas", formatDuration(employee.totalZoneSeconds)),
    createDetail("Tiempo counter", formatDuration(employee.counterSeconds)),
    createDetail("Interacciones", String(employee.interactionCount)),
    createDetail("Tiempo interacción", formatDuration(employee.totalInteractionSeconds)),
    createDetail("Celular >10 min", String(employee.phoneIncidentCount)),
    createDetail("Tiempo señal celular", formatDuration(employee.phoneIncidentSeconds)),
    createDetail("Primera detección", formatClock(employee.firstSeen)),
    createDetail(
      "Última detección",
      employee.status === "active" ? "Ahora" : formatClock(employee.lastSeen)
    ),
    createDetail("Sesiones", String(employee.sessionCount)),
    createDetail("Track actual", employee.trackerId == null ? "-" : `ID ${employee.trackerId}`)
  );

  const breakdown = document.createElement("div");
  breakdown.className = "zone-breakdown";

  const zoneRows = [...employee.zones];
  if (employee.unassignedSeconds > 0.5) {
    zoneRows.push({
      zoneId: "unassigned",
      zoneName: "Sin zona",
      seconds: employee.unassignedSeconds
    });
  }

  if (zoneRows.length === 0) {
    const empty = document.createElement("span");
    empty.className = "identity-empty";
    empty.textContent = "Sin permanencia en zonas registrada.";
    breakdown.appendChild(empty);
  } else {
    for (const zone of zoneRows) {
      breakdown.appendChild(createZoneRow(zone, employee.totalPresenceSeconds));
    }
  }

  card.append(heading, currentZone, details, breakdown);
  return card;
}

function filterIncidentsForDate(incidents, dateValue) {
  const bounds = getDayBounds(dateValue);
  const now = new Date();

  return incidents.filter((incident) => {
    const start = new Date(incident.started_at);
    const end = incident.status === "active"
      ? now
      : new Date(incident.ended_at ?? incident.confirmed_at ?? incident.last_seen_at);

    return datesOverlap(start, end, bounds.start, bounds.end);
  });
}

function isToday(dateValue) {
  return dateValue === localDateValue(new Date());
}

function createDetail(label, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "employee-detail";

  const key = document.createElement("span");
  key.textContent = label;

  const data = document.createElement("strong");
  data.textContent = value;

  wrapper.append(key, data);
  return wrapper;
}

function createZoneRow(zone, totalPresenceSeconds) {
  const row = document.createElement("div");
  row.className = "zone-row";

  const name = document.createElement("span");
  name.textContent = zone.zoneName;

  const bar = document.createElement("div");
  bar.className = "zone-bar";

  const fill = document.createElement("i");
  const percent = totalPresenceSeconds > 0
    ? Math.min(100, (zone.seconds / totalPresenceSeconds) * 100)
    : 0;
  fill.style.width = `${percent.toFixed(1)}%`;
  bar.appendChild(fill);

  const duration = document.createElement("strong");
  duration.textContent = formatDuration(zone.seconds);

  row.append(name, bar, duration);
  return row;
}

function getDayBounds(value) {
  const [year, month, day] = value.split("-").map(Number);
  const start = new Date(year, month - 1, day, 0, 0, 0, 0);
  const end = new Date(year, month - 1, day + 1, 0, 0, 0, 0);
  return { start, end };
}

function datesOverlap(start, end, rangeStart, rangeEnd) {
  return start < rangeEnd && end >= rangeStart;
}

function localDateValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDuration(value) {
  const totalSeconds = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

function formatClock(value) {
  if (!value) return "-";
  const date = value instanceof Date ? value : new Date(value);
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

window.setInterval(refreshSummary, REFRESH_MS);
void refreshSummary();

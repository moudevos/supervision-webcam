const video = document.querySelector("#camera");
const overlay = document.querySelector("#overlay");
const cameraStage = document.querySelector(".camera-stage");
const startZoneButton = document.querySelector("#startZoneButton");
const saveZoneButton = document.querySelector("#saveZoneButton");
const cancelZoneButton = document.querySelector("#cancelZoneButton");
const zoneStatus = document.querySelector("#zoneStatus");

if (video && overlay && cameraStage) {
  const nativeOverlayRect = overlay.getBoundingClientRect.bind(overlay);
  const guideCanvas = document.createElement("canvas");
  const guideContext = guideCanvas.getContext("2d");

  guideCanvas.className = "zone-editor-guide";
  Object.assign(guideCanvas.style, {
    position: "absolute",
    inset: "0",
    width: "100%",
    height: "100%",
    pointerEvents: "none",
    zIndex: "4"
  });
  cameraStage.appendChild(guideCanvas);

  let guidePoints = [];
  let hoverPoint = null;

  function getVideoContentRect() {
    const elementRect = nativeOverlayRect();
    const sourceWidth = video.videoWidth || overlay.width;
    const sourceHeight = video.videoHeight || overlay.height;

    if (!sourceWidth || !sourceHeight || !elementRect.width || !elementRect.height) {
      return new DOMRect(
        elementRect.left,
        elementRect.top,
        elementRect.width,
        elementRect.height
      );
    }

    const scale = Math.min(
      elementRect.width / sourceWidth,
      elementRect.height / sourceHeight
    );
    const width = sourceWidth * scale;
    const height = sourceHeight * scale;
    const left = elementRect.left + (elementRect.width - width) / 2;
    const top = elementRect.top + (elementRect.height - height) / 2;

    return new DOMRect(left, top, width, height);
  }

  // main.js converts pointer coordinates using overlay.getBoundingClientRect().
  // Return the real object-fit: contain video rectangle instead of the full stage.
  overlay.getBoundingClientRect = getVideoContentRect;

  function isEditing() {
    return overlay.classList.contains("overlay--editing");
  }

  function insideVideo(event) {
    const rect = getVideoContentRect();
    return (
      event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom
    );
  }

  function toStagePoint(event) {
    const stageRect = cameraStage.getBoundingClientRect();
    return {
      x: event.clientX - stageRect.left,
      y: event.clientY - stageRect.top
    };
  }

  function resizeGuide() {
    const rect = cameraStage.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    guideCanvas.width = Math.max(1, Math.round(rect.width * dpr));
    guideCanvas.height = Math.max(1, Math.round(rect.height * dpr));
    guideContext.setTransform(dpr, 0, 0, dpr, 0, 0);
    renderGuide();
  }

  function renderGuide() {
    const rect = cameraStage.getBoundingClientRect();
    guideContext.clearRect(0, 0, rect.width, rect.height);

    if (!isEditing() || guidePoints.length === 0) return;

    guideContext.save();
    guideContext.lineCap = "round";
    guideContext.lineJoin = "round";
    guideContext.font = "700 12px system-ui";

    for (let index = 1; index < guidePoints.length; index += 1) {
      drawDirectedSegment(guidePoints[index - 1], guidePoints[index]);
    }

    if (guidePoints.length >= 3) {
      guideContext.save();
      guideContext.setLineDash([7, 6]);
      guideContext.strokeStyle = "rgba(124, 252, 138, 0.55)";
      guideContext.lineWidth = 2;
      guideContext.beginPath();
      guideContext.moveTo(guidePoints[guidePoints.length - 1].x, guidePoints[guidePoints.length - 1].y);
      guideContext.lineTo(guidePoints[0].x, guidePoints[0].y);
      guideContext.stroke();
      guideContext.restore();
    }

    if (hoverPoint && guidePoints.length > 0) {
      guideContext.save();
      guideContext.setLineDash([5, 5]);
      guideContext.strokeStyle = "rgba(255, 255, 255, 0.8)";
      guideContext.lineWidth = 2;
      guideContext.beginPath();
      const last = guidePoints[guidePoints.length - 1];
      guideContext.moveTo(last.x, last.y);
      guideContext.lineTo(hoverPoint.x, hoverPoint.y);
      guideContext.stroke();
      guideContext.restore();
    }

    guidePoints.forEach((point, index) => drawPointBadge(point, index + 1));
    guideContext.restore();
  }

  function drawDirectedSegment(from, to) {
    guideContext.strokeStyle = "rgba(124, 252, 138, 0.95)";
    guideContext.lineWidth = 3;
    guideContext.beginPath();
    guideContext.moveTo(from.x, from.y);
    guideContext.lineTo(to.x, to.y);
    guideContext.stroke();

    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const length = Math.hypot(dx, dy);
    if (length < 28) return;

    const angle = Math.atan2(dy, dx);
    const x = from.x + dx * 0.58;
    const y = from.y + dy * 0.58;
    const size = 8;

    guideContext.fillStyle = "#ffffff";
    guideContext.beginPath();
    guideContext.moveTo(x + Math.cos(angle) * size, y + Math.sin(angle) * size);
    guideContext.lineTo(
      x + Math.cos(angle + 2.55) * size,
      y + Math.sin(angle + 2.55) * size
    );
    guideContext.lineTo(
      x + Math.cos(angle - 2.55) * size,
      y + Math.sin(angle - 2.55) * size
    );
    guideContext.closePath();
    guideContext.fill();
  }

  function drawPointBadge(point, number) {
    guideContext.fillStyle = "#07110a";
    guideContext.strokeStyle = "#ffffff";
    guideContext.lineWidth = 2;
    guideContext.beginPath();
    guideContext.arc(point.x, point.y, 11, 0, Math.PI * 2);
    guideContext.fill();
    guideContext.stroke();

    const label = String(number);
    const metrics = guideContext.measureText(label);
    guideContext.fillStyle = "#ffffff";
    guideContext.fillText(
      label,
      point.x - metrics.width / 2,
      point.y + 4
    );
  }

  overlay.addEventListener("pointermove", (event) => {
    if (!isEditing()) return;
    hoverPoint = insideVideo(event) ? toStagePoint(event) : null;
    renderGuide();
  });

  overlay.addEventListener("pointerleave", () => {
    hoverPoint = null;
    renderGuide();
  });

  overlay.addEventListener("click", (event) => {
    if (!isEditing() || !insideVideo(event)) return;
    guidePoints.push(toStagePoint(event));
    hoverPoint = null;
    renderGuide();
  });

  startZoneButton?.addEventListener("click", () => {
    guidePoints = [];
    hoverPoint = null;
    if (overlay.classList.contains("overlay--editing")) {
      zoneStatus.textContent =
        "Marca los puntos en orden. Los números y flechas muestran la dirección; la línea punteada anticipa el siguiente tramo.";
    }
    renderGuide();
  });

  cancelZoneButton?.addEventListener("click", () => {
    guidePoints = [];
    hoverPoint = null;
    renderGuide();
  });

  saveZoneButton?.addEventListener("click", () => {
    guidePoints = [];
    hoverPoint = null;
    renderGuide();
  });

  window.addEventListener("resize", resizeGuide);
  video.addEventListener("loadedmetadata", resizeGuide);
  resizeGuide();
}

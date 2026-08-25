# Supervision Webcam

MVP web local para detección, tracking temporal, reconocimiento facial, presencia y permanencia por zonas desde la cámara del navegador.

## Alcance actual

El proyecto ya implementa:

1. Webcam desde el navegador.
2. Detección de personas con YOLOX Nano ONNX.
3. Tracking temporal con Supervision + ByteTrack.
4. Estados `visible`, `lost` y `out` por `tracker_id`.
5. Tiempo temporal por track.
6. Registro facial local.
7. Detección facial con YuNet.
8. Embeddings y comparación facial con SFace.
9. Asociación `tracker_id -> identidad` mediante varias coincidencias consecutivas.
10. Historial persistente de presencia con SQLite.
11. Eventos `ENTER`, `IDENTIFIED`, `LOST`, `RETURNED` y `EXIT`.
12. Configuración visual de zonas poligonales sobre la cámara.
13. Coordenadas de zona normalizadas de `0..1`.
14. Detección de zona usando el punto inferior-central del bounding box.
15. Sesiones de permanencia por zona con eventos `ENTER_ZONE` y `EXIT_ZONE`.
16. UI con zona actual y tiempo de permanencia por persona.

Todavía no incluye métricas de interacción persona-persona, clasificación de actividad ni IA generativa.

## Arquitectura

```text
Browser / Webcam
      |
      v
Vite + JavaScript
      |
      | JPEG frame
      v
FastAPI / Python
      |
      +--> YOLOX Nano --> ByteTrack --> TrackStateManager
      |
      +--> YuNet --> SFace --> FaceRegistry --> IdentityManager
      |                                      |
      |                                      v
      |                               PresenceManager
      |                                      |
      |                                      v
      |                                  ZoneManager
      |                                      |
      +--------------------------------------+
                                             |
                                             v
                                      SQLite presence.db
                                             |
                                             +--> presence sessions/events
                                             +--> zones
                                             +--> zone sessions/events
```

## Requisitos

- Python 3.12 recomendado
- Node.js 20+
- Webcam

## Backend

```bash
cd backend
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/download_model.py
uvicorn app.main:app --reload --port 8000
```

El script descarga:

- `yolox_nano.onnx`
- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`

Comprobar:

```text
http://localhost:8000/health
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Abrir:

```text
http://localhost:5173
```

## Registro facial

1. Enciende la cámara.
2. Escribe el nombre de la persona.
3. Asegúrate de que solo haya un rostro visible.
4. Pulsa `Registrar rostro`.
5. Registra idealmente 3 a 5 muestras con pequeñas variaciones.

No se guardan fotografías. Los embeddings se almacenan en:

```text
backend/data/face_registry.json
```

## Historial de presencia

Cuando una identidad queda confirmada, se abre una sesión vinculada a su `identity_id`, no al `tracker_id`.

```text
Mauricio
  identity_id = identidad estable
  tracker_id  = trayectoria temporal de ByteTrack
```

SQLite se crea automáticamente en:

```text
backend/data/presence.db
```

No se registra un row por frame. Solo se persisten la sesión y cambios relevantes:

```text
ENTER
IDENTIFIED
LOST
RETURNED
EXIT
```

Historial API:

```text
GET /api/presence/history?session_limit=30&event_limit=80
```

## Zonas

Las zonas se dibujan desde la interfaz:

1. Enciende la cámara.
2. Escribe un nombre, por ejemplo `Atención`.
3. Pulsa `Dibujar zona`.
4. Marca al menos 3 puntos sobre la cámara.
5. Pulsa `Guardar`.

El frontend convierte los clics a coordenadas normalizadas. Por ejemplo:

```json
[
  [0.10, 0.30],
  [0.40, 0.30],
  [0.42, 0.90],
  [0.08, 0.90]
]
```

Así el polígono no depende de que la cámara esté a 1280x720 o 1920x1080.

La posición de una persona no usa el centro del torso. Se usa el punto inferior-central del bounding box:

```text
┌────────────┐
│   persona  │
│            │
└─────●──────┘
      posición
```

Cuando una identidad con sesión de presencia entra en una zona, se abre una `zone_session`. Al cambiar de zona o salir, se cierra y se registra el evento correspondiente.

```text
ENTER_ZONE
EXIT_ZONE
```

Las zonas desactivadas dejan de participar en detección, pero sus sesiones históricas se conservan.

API:

```text
GET  /api/zones
POST /api/zones
POST /api/zones/{zone_id}/delete
GET  /api/zones/history?session_limit=50&event_limit=120
```

## Modelos y licencias

- YOLOX: Apache 2.0.
- YuNet: MIT.
- SFace: Apache 2.0.
- Supervision: MIT.

Los pesos ONNX y los datos biométricos/runtime no se versionan en Git.

## Siguiente módulo

Después de validar zonas y permanencia, el siguiente paso es interacción: proximidad entre personas, duración de atención, ocupación por zona y eventos persona-persona.

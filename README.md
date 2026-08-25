# Supervision Webcam

MVP web local para detección, tracking temporal, reconocimiento facial e historial de presencia desde la cámara del navegador.

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
12. UI con sesiones activas y sesiones recientes.

Todavía no incluye zonas, métricas de actividad/interacción ni IA generativa.

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
      |                               SQLite presence.db
      v
JSON detections + tracks + identity + presence session
      |
      v
Canvas + panel + historial
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
  identity_id = empleado estable
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

Reglas actuales:

- Una pérdida breve mantiene la misma sesión.
- Al pasar a `lost`, se registra `LOST` una sola vez.
- Si vuelve antes de salir definitivamente, se registra `RETURNED` y continúa la sesión.
- Cuando el track pasa a `out`, se cierra la sesión con `EXIT`.
- Si vuelve después de cerrarse, el reconocimiento puede crear una nueva sesión para la misma identidad aunque ByteTrack use otro ID.
- Al detener/reiniciar la cámara se cierran las sesiones activas.
- Si el backend se reinicia de forma inesperada, las sesiones que quedaron abiertas se recuperan y se cierran usando su última detección conocida.

Historial API:

```text
GET /api/presence/history?session_limit=30&event_limit=80
```

## Modelos y licencias

- YOLOX: Apache 2.0.
- YuNet: MIT.
- SFace: Apache 2.0.
- Supervision: MIT.

Los pesos ONNX y los datos biométricos/runtime no se versionan en Git.

## Siguiente módulo

El siguiente paso natural es definir zonas de interés y medir permanencia por zona usando la identidad ya confirmada y las sesiones persistentes.

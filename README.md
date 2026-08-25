# Supervision Webcam

MVP web local para detección, tracking temporal, reconocimiento facial, presencia, zonas e interacciones desde la cámara del navegador.

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
16. Pantallas separadas de cámara, resumen operativo e historial.
17. Detección temporal de interacción empleado-persona desconocida.
18. Persistencia de sesiones y eventos de interacción.
19. Métricas de distancia mínima/promedio y duración de interacción.

Todavía no incluye clasificación de actividad/postura, ReID de clientes ni IA generativa.

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
      |                                      v
      |                              InteractionManager
      |                                      |
      +--------------------------------------+
                                             |
                                             v
                                      SQLite presence.db
                                             |
                                             +--> presence sessions/events
                                             +--> zones + zone sessions/events
                                             +--> interaction sessions/events
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

Vistas:

```text
http://localhost:5173/               cámara
http://localhost:5173/summary.html   resumen operativo
http://localhost:5173/history.html   historial
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

Las zonas se dibujan desde la interfaz y se almacenan como coordenadas normalizadas. La posición de una persona usa el punto inferior-central del bounding box:

```text
┌────────────┐
│   persona  │
│            │
└─────●──────┘
      posición
```

Cuando una identidad con sesión de presencia entra en una zona, se abre una `zone_session`. Al cambiar de zona o salir, se cierra y se registra:

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

## Interacciones

El módulo de interacción trabaja después de reconocimiento, presencia y zonas.

La primera versión registra únicamente:

```text
empleado reconocido <-> persona desconocida
```

No cuenta todavía interacciones entre dos empleados reconocidos. Un track con identidad facial todavía en estado `candidate` tampoco se trata como cliente potencial.

La distancia se calcula entre los puntos inferiores de ambos bounding boxes y se expresa como fracción del ancho del frame. Configuración inicial:

```text
distancia máxima       0.18 del ancho del frame
confirmación           3.0 segundos cerca
tolerancia de salida   2.0 segundos
```

Por tanto, cruzarse frente a otro track durante un instante no crea una interacción. Solo al mantener proximidad durante el tiempo de confirmación se crea una sesión persistente.

La sesión guarda:

```text
presence_session_id
identity_id del empleado
employee_tracker_id
other_tracker_id
zona
inicio de proximidad
momento de confirmación
última proximidad
fin
duración
distancia mínima
distancia promedio
cantidad de muestras
```

Eventos:

```text
INTERACTION_START
INTERACTION_END
```

API:

```text
GET /api/interactions/active
GET /api/interactions/history?session_limit=80&event_limit=160
```

Los tracks reconocidos devueltos por `/api/vision/detect` incluyen además:

```text
interaction_candidate_count
active_interactions[]
```

Limitación actual: una persona desconocida sigue vinculada a su `tracker_id`. Si ByteTrack pierde definitivamente ese ID y crea otro, todavía no existe ReID para unir ambas apariciones como la misma persona.

## Modelos y licencias

- YOLOX: Apache 2.0.
- YuNet: MIT.
- SFace: Apache 2.0.
- Supervision: MIT.

Los pesos ONNX y los datos biométricos/runtime no se versionan en Git.

## Siguiente módulo

Después de calibrar interacciones, el siguiente backend será métricas operativas agregadas y posteriormente clasificación de actividad/postura.
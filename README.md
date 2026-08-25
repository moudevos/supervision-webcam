# Supervision Webcam

MVP web local para detección, tracking temporal, reconocimiento facial, presencia, zonas, interacciones y supervisión operativa desde la cámara del navegador.

## Alcance actual

El proyecto implementa:

1. Webcam desde el navegador.
2. Detección con YOLOX Nano ONNX.
3. Tracking temporal con Supervision + ByteTrack.
4. Estados `visible`, `lost` y `out` por `tracker_id`.
5. Registro y reconocimiento facial local con YuNet + SFace.
6. Asociación `tracker_id -> identidad`.
7. Presencia persistente e historial SQLite.
8. Zonas poligonales normalizadas.
9. Permanencia por zona.
10. Filtro de perspectiva por tamaño relativo de persona.
11. Interacciones temporales empleado-persona desconocida.
12. Resumen e historial en pantallas separadas.
13. Estado operativo del módulo.
14. Detección de módulo vacío/abandonado.
15. Presencia y tiempo en zona de counter cuando se configura una zona correspondiente.
16. Señal experimental de celular asociada a empleados reconocidos.
17. Incidencia `PHONE_USE_LONG` después del umbral configurado, 10 minutos por defecto.

No están implementados todavía:

- estimación de pose/postura;
- detección fiable de audífonos;
- ReID persistente de clientes;
- homografía/calibración métrica del piso;
- IA generativa.

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
      +--> YOLOX Nano ----------------------+--> cell phone signal
      |         |
      |         +--> person --> ByteTrack --> TrackStateManager
      |
      +--> YuNet --> SFace --> IdentityManager
                              |
                              v
                       PresenceManager
                              |
                              v
                          ZoneManager
                              |
                +-------------+-------------+
                |                           |
                v                           v
        OperationalManager          InteractionManager
                |
                v
         BehaviorManager
                |
                v
        SQLite presence.db
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
http://localhost:5173/               cámara/configuración
http://localhost:5173/summary.html   resumen operativo en tiempo real
http://localhost:5173/history.html   historial y línea temporal
```

## Persistencia

No se guardan frames ni fotografías de seguimiento.

Embeddings faciales:

```text
backend/data/face_registry.json
```

Datos temporales/persistentes:

```text
backend/data/presence.db
```

SQLite contiene presencia, zonas, interacciones, incidencias operativas y señales de comportamiento confirmadas.

## Zonas y perspectiva

La posición usa el punto inferior-central del bounding box:

```text
┌────────────┐
│   persona  │
│            │
└─────●──────┘
      posición
```

Además se calcula:

```text
person_height_ratio = altura_bbox / altura_frame
```

Una persona con un `person_height_ratio` inferior a `ZONE_MIN_PERSON_HEIGHT_RATIO` no puede activar una zona. El valor inicial es `0.08`.

Esto es un filtro práctico para reducir falsas asignaciones de personas lejanas del pasillo/fondo. No sustituye una calibración geométrica del piso. Si se necesita precisión espacial robusta, el siguiente nivel es una homografía usando puntos de referencia del piso.

## Interacciones

La primera versión registra únicamente:

```text
empleado reconocido <-> persona desconocida
```

Reglas iniciales:

```text
INTERACTION_DISTANCE_THRESHOLD=0.18
INTERACTION_CONFIRM_SECONDS=3.0
INTERACTION_EXIT_GRACE_SECONDS=2.0
```

Eventos:

```text
INTERACTION_START
INTERACTION_END
```

API:

```text
GET /api/interactions/active
GET /api/interactions/history
```

## Supervisión operativa

### Módulo vacío / abandono

La regla no usa `personas_en_frame == 0`. Solo evalúa empleados reconocidos dentro de zonas operativas y que superan el filtro de perspectiva.

El monitor de abandono se arma después de observar por primera vez un empleado reconocido dentro del módulo. Así el sistema no registra un falso abandono simplemente porque la cámara se inició antes de la llegada del personal.

Después de quedar vacío durante:

```text
MODULE_EMPTY_CONFIRM_SECONDS=30.0
```

se crea:

```text
MODULE_ABANDONED
MODULE_ABANDONED_START
MODULE_ABANDONED_END
```

Si `OPERATIONAL_MODULE_ZONE_NAMES` queda vacío, todas las zonas activas forman el módulo. Si se especifican nombres, solo se usan los que realmente existen entre las zonas activas.

API:

```text
GET /api/operations/status
GET /api/operations/history
```

### Counter / mostrador

El counter no se infiere por la imagen ni por el nombre `zona 1/2/3`. Debe configurarse explícitamente por nombre:

```dotenv
OPERATIONAL_COUNTER_ZONE_NAMES=nombre_real_de_la_zona
```

Si ninguno de los nombres configurados coincide con una zona activa, el resumen muestra el counter como no configurado.

## Señal de celular

YOLOX COCO ya incluye la clase `cell phone`, por lo que la misma inferencia detecta personas y teléfonos sin añadir otro framework.

La señal solo se procesa cuando:

- el teléfono puede asociarse espacialmente a un bounding box de persona;
- esa persona está reconocida como empleado;
- el empleado está dentro del módulo operativo;
- la señal se mantiene temporalmente.

Configuración inicial:

```dotenv
PHONE_DETECTION_THRESHOLD=0.20
PHONE_ASSOCIATION_MARGIN_RATIO=0.08
PHONE_USE_CONFIRM_SECONDS=600.0
PHONE_USE_GAP_GRACE_SECONDS=5.0
```

Después de 600 segundos se crea una incidencia:

```text
PHONE_USE_LONG
PHONE_USE_LONG_START
PHONE_USE_LONG_END
```

Importante: esta señal significa `cell phone visible asociado al empleado durante el umbral`. No demuestra qué estaba haciendo el empleado ni debe interpretarse automáticamente como incumplimiento. Los teléfonos pequeños u ocultos también pueden generar falsos negativos con YOLOX Nano a 416 px.

API:

```text
GET /api/behaviors/status
GET /api/behaviors/history
```

## Resumen e historial

`summary.html` se actualiza periódicamente y consolida por empleado:

- presencia;
- zona actual;
- tiempo por zona;
- tiempo en counter;
- interacciones;
- tiempo en interacción;
- celular visible actualmente;
- incidencias de celular por encima del umbral;
- estado global del módulo;
- abandonos registrados.

`history.html` contiene tablas y línea de tiempo para presencia, zonas, interacciones, comportamientos e incidencias operativas.

## Modelos y licencias

- YOLOX: Apache 2.0.
- YuNet: MIT.
- SFace: Apache 2.0.
- Supervision: MIT.

Los pesos ONNX y los datos biométricos/runtime no se versionan en Git.

## Próximos módulos

1. Calibrar perspectiva y, si hace falta, introducir homografía del plano del piso.
2. Añadir pose/keypoints para postura con un modelo ONNX local.
3. Definir reglas de postura concretas antes de calificarlas como incorrectas.
4. Añadir un detector específico de audífonos; la clase no existe en COCO YOLOX.
5. Motor de reglas/alertas que combine identidad, zona, duración, interacción y comportamiento.
6. Multi-cámara con estado aislado por `camera_id`.

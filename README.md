# Supervision Webcam

MVP web local para detección, tracking temporal y reconocimiento facial desde la cámara del navegador.

## Alcance actual

El proyecto ya implementa:

1. Webcam desde el navegador.
2. Detección de personas con YOLOX Nano ONNX.
3. Tracking temporal con Supervision + ByteTrack.
4. Estados `visible`, `lost` y `out` por `tracker_id`.
5. Tiempo de sesión por track.
6. Registro facial local.
7. Detección facial con YuNet.
8. Embeddings y comparación facial con SFace.
9. Asociación `tracker_id -> identidad` mediante varias coincidencias consecutivas.
10. UI en tiempo real con nombre confirmado o persona sin identificar.

Todavía no incluye historial persistente de sesiones, zonas, métricas laborales ni IA generativa.

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
      |
      v
JSON detections + tracks + identity
      |
      v
Canvas + panel en tiempo real
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

Para reconocimiento facial debe aparecer:

```json
{
  "face_recognition_ready": true
}
```

## Frontend

En otra terminal:

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
5. Registra idealmente 3 a 5 muestras con pequeñas variaciones de ángulo e iluminación.

No se guardan fotografías durante este MVP. Se almacenan únicamente embeddings numéricos en:

```text
backend/data/face_registry.json
```

Ese archivo está excluido de Git.

## Reconocimiento

El reconocimiento no se ejecuta en cada frame. Se realiza periódicamente y requiere varias coincidencias consecutivas antes de confirmar una identidad para un `tracker_id`.

Ejemplo:

```text
Track ID 4
   -> candidato Mauricio
   -> coincidencia 1
   -> coincidencia 2
   -> coincidencia 3
   -> identidad confirmada: Mauricio
```

Si la persona sale y vuelve con otro track, el reconocimiento puede volver a asociar ese nuevo `tracker_id` con la misma identidad registrada.

## Modelos y licencias

- YOLOX: Apache 2.0.
- YuNet: MIT.
- SFace: Apache 2.0.
- Supervision: MIT.

Los pesos ONNX no se versionan en este repositorio.

## Siguiente módulo

El siguiente paso es historial persistente: almacenar sesiones y eventos vinculados a una identidad confirmada, sin usar el `tracker_id` como identidad permanente.

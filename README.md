# Supervision Webcam

MVP web para detección de personas en tiempo real usando la cámara del navegador y un backend local de visión por computadora.

## Alcance actual

Este primer módulo hace únicamente:

1. Abrir la webcam desde el navegador.
2. Capturar frames en el frontend.
3. Enviar frames al backend FastAPI.
4. Ejecutar detección de personas con YOLOX Nano ONNX.
5. Normalizar detecciones con Supervision.
6. Dibujar bounding boxes en el navegador.

Todavía no incluye tracking, reconocimiento facial, base de datos, métricas ni IA generativa.

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
      v
YOLOX Nano + ONNX Runtime
      |
      v
Supervision
      |
      | JSON detections
      v
Canvas overlay
```

## Requisitos

- Python 3.11+
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

## Variables de entorno

El backend funciona con valores por defecto. Para personalizarlo, copia `.env.example` a `.env` y ajusta las variables necesarias.

## Modelo

El script `backend/scripts/download_model.py` descarga `yolox_nano.onnx` desde el release oficial de YOLOX. Los pesos no se versionan en Git.

## Siguiente módulo

Cuando detección y latencia sean aceptables, el siguiente paso será tracking persistente de personas entre frames.

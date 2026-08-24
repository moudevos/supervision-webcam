from pathlib import Path

import httpx


MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "yolox_nano.onnx"


def main() -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

    if MODEL_PATH.exists():
        print(f"Model already exists: {MODEL_PATH}")
        return

    print("Downloading YOLOX Nano ONNX...")

    with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=120.0) as response:
        response.raise_for_status()
        with MODEL_PATH.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)

    print(f"Model saved to: {MODEL_PATH}")


if __name__ == "__main__":
    main()

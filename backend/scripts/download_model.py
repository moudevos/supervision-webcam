from pathlib import Path

import httpx


MODELS = [
    (
        "YOLOX Nano",
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx",
        "yolox_nano.onnx",
    ),
    (
        "YuNet face detector",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "face_detection_yunet_2023mar.onnx",
    ),
    (
        "SFace face recognizer",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "face_recognition_sface_2021dec.onnx",
    ),
]

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"


def download_model(name: str, url: str, filename: str) -> None:
    target = MODELS_DIR / filename

    if target.exists() and target.stat().st_size > 100_000:
        print(f"[OK] {name}: {target}")
        return

    print(f"Downloading {name}...")
    temp = target.with_suffix(target.suffix + ".part")

    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as response:
        response.raise_for_status()
        with temp.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)

    if temp.stat().st_size < 100_000:
        content = temp.read_bytes()[:200]
        temp.unlink(missing_ok=True)
        if b"git-lfs.github.com/spec" in content:
            raise RuntimeError(
                f"{name}: GitHub devolvió un puntero Git LFS en vez del modelo."
            )
        raise RuntimeError(f"{name}: el archivo descargado parece incompleto.")

    temp.replace(target)
    print(f"[OK] {name}: {target}")


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for name, url, filename in MODELS:
        download_model(name, url, filename)

    print("All models are ready.")


if __name__ == "__main__":
    main()

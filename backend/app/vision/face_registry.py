from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import numpy as np

from app.core.config import settings


class FaceRegistry:
    """Small local registry for face embeddings. No raw face images are stored."""

    def __init__(self) -> None:
        self.path: Path = settings.resolved_face_registry_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._people: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._people = []
            return

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._people = payload.get("people", [])
        except (json.JSONDecodeError, OSError):
            self._people = []

    def _save(self) -> None:
        payload = {"people": self._people}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_sample(self, name: str, embedding: np.ndarray) -> dict:
        clean_name = " ".join(name.strip().split())
        if len(clean_name) < 2:
            raise ValueError("Ingresa un nombre válido.")

        person = next(
            (
                item
                for item in self._people
                if item["name"].casefold() == clean_name.casefold()
            ),
            None,
        )

        if person is None:
            person = {
                "id": str(uuid4()),
                "name": clean_name,
                "samples": [],
            }
            self._people.append(person)

        samples = person["samples"]
        samples.append(embedding.astype(float).tolist())

        max_samples = settings.face_max_samples_per_identity
        if len(samples) > max_samples:
            person["samples"] = samples[-max_samples:]

        self._save()
        return {
            "identity_id": person["id"],
            "name": person["name"],
            "sample_count": len(person["samples"]),
        }

    def match(self, embedding: np.ndarray) -> dict | None:
        best: dict | None = None

        for person in self._people:
            for sample in person.get("samples", []):
                reference = np.asarray(sample, dtype=np.float32)
                if reference.shape != embedding.shape:
                    continue

                score = float(np.dot(embedding, reference))
                if best is None or score > best["score"]:
                    best = {
                        "identity_id": person["id"],
                        "name": person["name"],
                        "score": score,
                    }

        if best is None or best["score"] < settings.face_match_threshold:
            return None

        return best

    def list_people(self) -> list[dict]:
        return [
            {
                "identity_id": person["id"],
                "name": person["name"],
                "sample_count": len(person.get("samples", [])),
            }
            for person in sorted(self._people, key=lambda item: item["name"].casefold())
        ]

    @property
    def empty(self) -> bool:
        return len(self._people) == 0


face_registry = FaceRegistry()

"""Local library for audio recordings imported into Stove."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

MAX_RECORDING_BYTES = 64 * 1024 * 1024
EXTENSIONS = {".aac", ".amr", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".3gp"}
MIME = {".aac": "audio/aac", ".amr": "audio/amr", ".flac": "audio/flac",
        ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
        ".opus": "audio/ogg", ".wav": "audio/wav", ".3gp": "audio/3gpp"}


class RecordingLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        items = []
        for sidecar in self.root.glob("*.json"):
            try:
                item = json.loads(sidecar.read_text(encoding="utf-8"))
                if not re.fullmatch(r"[0-9a-f]{32}", item["id"]):
                    continue
                if not (self.root / (item["id"] + item["extension"])).is_file():
                    continue
                items.append(item)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(items, key=lambda item: item["created"], reverse=True)

    def import_stream(self, stream, filename: str, size: int) -> dict:
        name = Path(filename).name.strip()
        extension = Path(name).suffix.lower()
        if not name or extension not in EXTENSIONS or not 0 < size <= MAX_RECORDING_BYTES:
            raise ValueError("Choose an audio file up to 64 MB")
        identifier = uuid.uuid4().hex
        destination = self.root / (identifier + extension)
        temporary = self.root / (identifier + ".partial")
        try:
            with temporary.open("xb") as output:
                remaining = size
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Incomplete audio upload")
                    output.write(chunk)
                    remaining -= len(chunk)
            os.replace(temporary, destination)
            item = {"id": identifier, "name": name[:160], "extension": extension,
                    "size": size, "created": time.time()}
            sidecar = self.root / (identifier + ".json")
            sidecar.write_text(json.dumps(item), encoding="utf-8")
            return item
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    def save_recording(self, filename: str, data: bytes) -> dict:
        name = Path(filename).name.strip()
        extension = Path(name).suffix.lower()
        if not extension or extension not in EXTENSIONS:
            extension = ".mp3"
            if not name.endswith(".mp3"):
                name = f"{name}.mp3"
        size = len(data)
        if not 0 < size <= MAX_RECORDING_BYTES:
            raise ValueError("Choose an audio file up to 64 MB")
        identifier = uuid.uuid4().hex
        destination = self.root / (identifier + extension)
        temporary = self.root / (identifier + ".partial")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
            item = {"id": identifier, "name": name[:160], "extension": extension,
                    "size": size, "created": time.time()}
            sidecar = self.root / (identifier + ".json")
            sidecar.write_text(json.dumps(item), encoding="utf-8")
            return item
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    def resolve(self, identifier: str) -> tuple[dict, Path]:
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise FileNotFoundError
        sidecar = self.root / (identifier + ".json")
        item = json.loads(sidecar.read_text(encoding="utf-8"))
        path = self.root / (identifier + item["extension"])
        if item["id"] != identifier or item["extension"] not in EXTENSIONS or not path.is_file():
            raise FileNotFoundError
        return item, path

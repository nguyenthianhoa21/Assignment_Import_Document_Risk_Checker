import os
import uuid
from pathlib import Path

from app.config import settings


def uploads_root() -> Path:
    path = Path(settings.upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def shipment_dir(shipment_id: uuid.UUID) -> Path:
    path = uploads_root() / str(shipment_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(shipment_id: uuid.UUID, file_name: str, content: bytes) -> str:
    safe_name = Path(file_name).name
    target_dir = shipment_dir(shipment_id)
    destination = target_dir / safe_name
    destination.write_bytes(content)
    return str(destination)

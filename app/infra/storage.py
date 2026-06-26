"""Proof image storage — bytes on local disk (the ₹0 option).

Uploaded complaint photos are written under `PROOF_STORAGE_DIR` (gitignored) with
a random, extension-only filename — never the user's filename, so there's no
path-traversal or collision risk. Swap in S3/R2 later by reimplementing
`save_upload`/`proof_path`; callers won't change.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

from app.core.config import settings

# Allowed image types -> file extension. Anything else is rejected on upload.
IMAGE_EXTS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/gif": ".gif",
}


def is_allowed_image(content_type: Optional[str]) -> bool:
    return bool(content_type) and content_type.split(";")[0].strip().lower() in IMAGE_EXTS


def proof_dir() -> Path:
    directory = Path(settings.proof_storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_upload(data: bytes, content_type: str) -> str:
    """Write the bytes under a random name; return the storage ref (filename).
    Assumes the content_type was validated with `is_allowed_image`."""
    ext = IMAGE_EXTS.get(content_type.split(";")[0].strip().lower(), ".bin")
    ref = f"{secrets.token_hex(16)}{ext}"
    (proof_dir() / ref).write_bytes(data)
    return ref


def proof_path(ref: str) -> Optional[Path]:
    """Resolve a stored ref to a path *inside* the proof dir, or None if malformed
    / escaping the dir (defence-in-depth against traversal)."""
    base = proof_dir().resolve()
    candidate = (base / ref).resolve()
    if base not in candidate.parents or not candidate.is_file():
        return None
    return candidate

"""Хранение raw-ответов: gzip JSON, до нормализации; replay без сети."""

from __future__ import annotations

import gzip
import json
import re
import secrets
from pathlib import Path

from .models import RawDocument

SECRET_RX = re.compile(
    r"(?im)^([^=\s]{0,40}(?:key|token|secret|password|authorization)[^=\s]{0,20})"
    r"\s*=\s*(\S+.{0,80})$")


def redact(text: str) -> str:
    def _sub(match):
        return f"{match.group(1)}=[REDACTED]"
    return SECRET_RX.sub(_sub, text)


def save_raw(root: Path, source: str, doc: RawDocument) -> str:
    request_id = doc.request_id or secrets.token_hex(8)
    date_part = doc.fetched_at[:10]
    folder = Path(root) / "raw" / source / date_part
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": doc.url,
        "status": doc.status,
        "fetched_at": doc.fetched_at,
        "headers": {k: redact(v) if k.lower() in ("authorization", "set-cookie",
                                                  "ocp-apim-subscription-key")
                    else v for k, v in doc.headers.items()},
        "content": redact(doc.content),
    }
    path = folder / f"{request_id}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return str(path)

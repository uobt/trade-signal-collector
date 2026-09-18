"""Загрузка конфигурации: JSON нативно (YAML вне первой версии)."""

from __future__ import annotations

import json
from pathlib import Path

from .models import TradeQuery, TradeSpec, TransportConfig


def load_spec(path: Path) -> TradeSpec:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    transport_raw = data.get("transport") or {}
    transport = TransportConfig(
        request_delay_seconds=float(transport_raw.get("request_delay_seconds", 2.0)),
        timeout_seconds=float(transport_raw.get("timeout_seconds", 30.0)),
        max_retries=int(transport_raw.get("max_retries", 2)),
    )
    queries = [
        TradeQuery(
            reporter=str(item.get("reporter", "")),
            partner=str(item.get("partner", "0")),
            flow=str(item.get("flow", "M")),
            hs=str(item.get("hs", "TOTAL")),
            periods=[str(p) for p in item.get("periods", [])],
        )
        for item in data.get("queries", [])
    ]
    return TradeSpec(
        queries=queries, transport=transport,
        max_rows_per_query=int(data.get("max_rows_per_query", 500)),
    )


def load_env(root: Path) -> dict[str, str]:
    """Минимальный .env-парсер: KEY=VALUE, без кавычек/интерполяции."""
    values: dict[str, str] = {}
    env_path = Path(root) / ".env"
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values

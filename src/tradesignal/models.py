"""Модели контуров A (статистика) и B (компании)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SourceBlocked(Exception):
    """Источник заблокирован: policy или technical. Обход запрещён."""

    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: {reason}")
        self.source, self.reason = source, reason


@dataclass
class TransportConfig:
    request_delay_seconds: float = 2.0
    timeout_seconds: float = 30.0
    max_retries: int = 2


@dataclass
class TradeQuery:
    """Один запрос статистики: отчётная страна, партнёр, HS, направление."""
    reporter: str            # ISO3 или 'all'
    partner: str             # ISO3, '0' = World
    flow: str                # 'M' импорт / 'X' экспорт
    hs: str                  # HS-код (2/4/6 знаков)
    periods: list[str] = field(default_factory=list)  # ['2023','2024'] или '2024-08'

    def validate(self) -> list[str]:
        errors = []
        if self.flow not in ("M", "X"):
            errors.append(f"flow должен быть M или X, получен {self.flow!r}")
        digits = sum(ch.isdigit() for ch in self.hs)
        if not (self.hs == "TOTAL" or digits in (2, 4, 6)):
            errors.append(f"hs должен быть 2/4/6 знаков или TOTAL, получен {self.hs!r}")
        for period in self.periods:
            if not (period.isdigit() and 1962 <= int(period) <= 2100) and \
                    not (_is_year_month(period)):
                errors.append(f"период {period!r}: ожидается год или YYYY-MM")
        return errors


def _is_year_month(period: str) -> bool:
    parts = period.split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return False
    year, month = int(parts[0]), int(parts[1])
    return 1962 <= year <= 2100 and 1 <= month <= 12


@dataclass
class TradeSpec:
    queries: list[TradeQuery] = field(default_factory=list)
    transport: TransportConfig = field(default_factory=TransportConfig)
    max_rows_per_query: int = 500

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.queries:
            errors.append("нет запросов")
        for index, query in enumerate(self.queries):
            for error in query.validate():
                errors.append(f"запрос[{index}]: {error}")
        if self.max_rows_per_query <= 0:
            errors.append("max_rows_per_query должен быть > 0")
        return errors


@dataclass
class RawDocument:
    url: str
    status: int
    content: str
    headers: dict[str, str] = field(default_factory=dict)
    request_id: str = ""
    fetched_at: str = field(default_factory=utcnow)


@dataclass
class StatRow:
    """Наблюдение ряда статистики: уникальность
    (source, reporter, partner, flow, hs, period)."""
    source: str
    reporter_iso: str
    partner_iso: str
    flow: str
    hs_code: str
    period: str
    value_usd: float | None = None
    qty: float | None = None
    qty_unit: str | None = None
    raw_ref: str | None = None
    observed_at: str = field(default_factory=utcnow)

    @property
    def hs_length(self) -> int:
        return len(self.hs_code) if self.hs_code != "TOTAL" else 0

    def key(self) -> tuple:
        return (self.source, self.reporter_iso, self.partner_iso,
                self.flow, self.hs_code, self.period)

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["hs_length"] = self.hs_length
        return row


@dataclass
class TradePage:
    rows: list[StatRow] = field(default_factory=list)
    next_cursor: str | None = None
    status: str = "success"        # success/partial/blocked/failed
    applied_filters: dict[str, Any] = field(default_factory=dict)
    unsupported_filters: list[str] = field(default_factory=list)
    raw_ref: str | None = None
    stop_reason: str | None = None
    note: str | None = None


@dataclass
class CompanyRecord:
    source: str
    source_key: str
    name: str
    name_norm: str = ""
    country: str | None = None
    website: str | None = None
    identity_confidence: str = "medium"   # high/medium/low
    first_seen_at: str = field(default_factory=utcnow)
    last_seen_at: str = field(default_factory=utcnow)

    def key(self) -> tuple:
        return (self.source, self.source_key)


# Известные freight forwarder'ы/3PL: consignee в манифестах — шум, не покупатель.
FORWARDERS = (
    "expeditors", "kuehne", "nagel", "dhl", "schenker", "dsv", "db schenker",
    "maersk", "msc ", "cma cgm", "hapag", "one line", "evergreen", "cosco",
    "panalpina", "geodis", "ceva", "agility", "damco", "ryder", "ups",
    "fedex", "tnt", "kintetsu", "yusen", "mitsui", "nyk", "savour", "bell",
    "logistics", "forwarding", "freight", "shipping", "transport",
)


def forwarder_suspect(name: str | None) -> bool:
    """Грубый флаг экспедиторского шума; сомнение решает человек, не слияние."""
    if not name:
        return False
    lowered = name.lower()
    return any(marker in lowered for marker in FORWARDERS)

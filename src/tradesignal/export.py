"""Экспорт: CSV UTF-8 BOM + formula-guard, JSONL."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

STAT_COLUMNS = [
    "source", "reporter_iso", "partner_iso", "flow", "hs_code", "hs_length",
    "period", "value_usd", "qty", "qty_unit", "observed_at",
]
SIGNAL_COLUMNS = [
    "kind", "reporter_iso", "partner_iso", "flow", "hs_code", "period",
    "value_before", "value_after", "pct", "hypothesis", "computed_at",
]
SHIPMENT_COLUMNS = [
    "company_source", "company_key", "company_name", "supplier_name",
    "supplier_country", "arrival_date", "port", "hs_codes",
    "weight_kg_declared", "quantity_declared", "ff_suspect",
]
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _guard(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _write_csv(rows: Iterable[dict | Any], out_path: Path,
               columns: Sequence[str]) -> int:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            record = row if isinstance(row, dict) else dict(row)
            writer.writerow([_guard(record.get(col)) for col in columns])
            written += 1
    return written


def export_stat_csv(rows, out_path: Path) -> int:
    return _write_csv(rows, out_path, STAT_COLUMNS)


def export_signals_csv(rows, out_path: Path) -> int:
    return _write_csv(rows, out_path, SIGNAL_COLUMNS)


def export_shipments_csv(rows, out_path: Path) -> int:
    return _write_csv(rows, out_path, SHIPMENT_COLUMNS)


def export_jsonl(rows: Iterable[dict | Any], out_path: Path) -> int:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            record = row if isinstance(row, dict) else dict(row)
            handle.write(json.dumps(record, ensure_ascii=False,
                                    default=str) + "\n")
            written += 1
    return written

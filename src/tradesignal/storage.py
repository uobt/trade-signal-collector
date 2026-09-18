"""SQLite: ряды статистики, компании, поставки, сигналы, прогоны."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .models import CompanyRecord, StatRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  source TEXT,
  config TEXT,
  status TEXT DEFAULT 'running',
  stop_reason TEXT,
  note TEXT,
  requests INTEGER DEFAULT 0,
  rows INTEGER DEFAULT 0,
  new_rows INTEGER DEFAULT 0,
  updated_rows INTEGER DEFAULT 0,
  started_at TEXT DEFAULT (datetime('now')),
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS stat_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  reporter_iso TEXT NOT NULL,
  partner_iso TEXT NOT NULL,
  flow TEXT NOT NULL,
  hs_code TEXT NOT NULL,
  hs_length INTEGER NOT NULL,
  period TEXT NOT NULL,
  value_usd REAL,
  qty REAL,
  qty_unit TEXT,
  raw_ref TEXT,
  observed_at TEXT,
  UNIQUE(source, reporter_iso, partner_iso, flow, hs_code, period)
);

CREATE TABLE IF NOT EXISTS stat_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observation_id INTEGER NOT NULL,
  value_usd REAL, qty REAL,
  observed_at TEXT
);

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_key TEXT NOT NULL,
  name TEXT NOT NULL,
  name_norm TEXT NOT NULL,
  country TEXT, website TEXT,
  identity_confidence TEXT DEFAULT 'medium',
  first_seen_at TEXT, last_seen_at TEXT,
  UNIQUE(source, source_key)
);

CREATE TABLE IF NOT EXISTS shipments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  supplier_name TEXT NOT NULL,
  supplier_country TEXT,
  arrival_date TEXT, port TEXT,
  hs_codes TEXT,
  weight_kg_declared REAL,
  quantity_declared REAL,
  ff_suspect INTEGER DEFAULT 0,
  raw_ref TEXT, observed_at TEXT,
  UNIQUE(source, company_id, arrival_date, supplier_name)
);

CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  reporter_iso TEXT, partner_iso TEXT, hs_code TEXT, period TEXT,
  value_before REAL, value_after REAL,
  pct REAL,
  hypothesis TEXT,
  computed_at TEXT DEFAULT (datetime('now'))
);
"""

ALLOWED_RUN_COLUMNS = {
    "status", "stop_reason", "note", "requests", "rows", "new_rows",
    "updated_rows", "finished_at",
}


class Store:
    def __init__(self, path: Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- прогоны -------------------------------------------------------
    def start_run(self, kind: str, config: str, source: str | None) -> int:
        with closing(self.conn.execute(
                "insert into runs(kind, config, source) values(?,?,?)",
                (kind, config, source))) as cur:
            self.conn.commit()
            return cur.lastrowid

    def note_run(self, run_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items()
                   if k in ALLOWED_RUN_COLUMNS}
        if not allowed:
            return
        sets = ", ".join(f"{k}=?" for k in allowed)
        self.conn.execute(f"update runs set {sets} where id=?",
                          (*allowed.values(), run_id))
        self.conn.commit()

    def finish_run(self, run_id: int, status: str, **fields) -> None:
        self.note_run(run_id, status=status, finished_at=_utc(), **fields)

    # --- контур A ------------------------------------------------------
    def upsert_stat(self, row: StatRow) -> str:
        """first_seen / updated / unchanged. Расхождение значений -> история."""
        existing = self.conn.execute(
            "select id, value_usd, qty from stat_observations "
            "where source=? and reporter_iso=? and partner_iso=? and flow=? "
            "and hs_code=? and period=?", row.key()).fetchone()
        if existing is None:
            self.conn.execute(
                "insert into stat_observations(source, reporter_iso, "
                "partner_iso, flow, hs_code, hs_length, period, value_usd, "
                "qty, qty_unit, raw_ref, observed_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                (row.source, row.reporter_iso, row.partner_iso, row.flow,
                 row.hs_code, row.hs_length, row.period, row.value_usd,
                 row.qty, row.qty_unit, row.raw_ref, row.observed_at))
            self.conn.commit()
            return "first_seen"
        changed = (existing["value_usd"] != row.value_usd
                   or existing["qty"] != row.qty)
        if changed:
            self.conn.execute(
                "insert into stat_history(observation_id, value_usd, qty, "
                "observed_at) values(?,?,?,?)",
                (existing["id"], existing["value_usd"], existing["qty"],
                 row.observed_at))
            self.conn.execute(
                "update stat_observations set value_usd=?, qty=?, qty_unit=?, "
                "raw_ref=?, observed_at=? where id=?",
                (row.value_usd, row.qty, row.qty_unit, row.raw_ref,
                 row.observed_at, existing["id"]))
            self.conn.commit()
            return "updated"
        self.conn.execute("update stat_observations set observed_at=? where id=?",
                          (row.observed_at, existing["id"]))
        self.conn.commit()
        return "unchanged"

    def stat_rows(self, source: str | None = None) -> list[sqlite3.Row]:
        if source:
            with closing(self.conn.execute(
                    "select * from stat_observations where source=? "
                    "order by reporter_iso, hs_code, period", (source,))) as cur:
                return cur.fetchall()
        with closing(self.conn.execute(
                "select * from stat_observations "
                "order by reporter_iso, hs_code, period")) as cur:
            return cur.fetchall()

    # --- контур B ------------------------------------------------------
    def upsert_company(self, record: CompanyRecord) -> str:
        existing = self.conn.execute(
            "select id from companies where source=? and source_key=?",
            record.key()).fetchone()
        if existing is None:
            self.conn.execute(
                "insert into companies(source, source_key, name, name_norm, "
                "country, website, identity_confidence, first_seen_at, "
                "last_seen_at) values(?,?,?,?,?,?,?,?,?)",
                (record.source, record.source_key, record.name,
                 record.name_norm, record.country, record.website,
                 record.identity_confidence, record.first_seen_at,
                 record.last_seen_at))
            self.conn.commit()
            return "first_seen"
        self.conn.execute(
            "update companies set name=?, name_norm=?, country=?, website=?, "
            "identity_confidence=?, last_seen_at=? where id=?",
            (record.name, record.name_norm, record.country, record.website,
             record.identity_confidence, record.last_seen_at, existing["id"]))
        self.conn.commit()
        return "updated"

    def company_id(self, source: str, source_key: str) -> int | None:
        row = self.conn.execute(
            "select id from companies where source=? and source_key=?",
            (source, source_key)).fetchone()
        return row["id"] if row else None

    def insert_shipment(self, source: str, company_id: int,
                        supplier_name: str, arrival_date: str,
                        supplier_country: str | None = None,
                        port: str | None = None,
                        hs_codes: str | None = None,
                        weight_kg_declared: float | None = None,
                        quantity_declared: float | None = None,
                        ff_suspect: bool = False,
                        raw_ref: str | None = None,
                        observed_at: str = "") -> str:
        existing = self.conn.execute(
            "select id from shipments where source=? and company_id=? and "
            "arrival_date=? and supplier_name=?",
            (source, company_id, arrival_date, supplier_name)).fetchone()
        if existing:
            return "unchanged"
        self.conn.execute(
            "insert into shipments(source, company_id, supplier_name, "
            "supplier_country, arrival_date, port, hs_codes, "
            "weight_kg_declared, quantity_declared, ff_suspect, raw_ref, "
            "observed_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
            (source, company_id, supplier_name, supplier_country,
             arrival_date, port, hs_codes, weight_kg_declared,
             quantity_declared, 1 if ff_suspect else 0, raw_ref,
             observed_at))
        self.conn.commit()
        return "first_seen"

    # --- сигналы -------------------------------------------------------
    def insert_signal(self, kind: str, reporter: str, partner: str,
                      hs: str, period: str, before, after, pct,
                      hypothesis: str | None) -> None:
        self.conn.execute(
            "insert into signals(kind, reporter_iso, partner_iso, hs_code, "
            "period, value_before, value_after, pct, hypothesis) "
            "values(?,?,?,?,?,?,?,?,?)",
            (kind, reporter, partner, hs, period, before, after, pct,
             hypothesis))
        self.conn.commit()

    def signals(self) -> list[sqlite3.Row]:
        with closing(self.conn.execute(
                "select * from signals order by reporter_iso, hs_code, period")) as cur:
            return cur.fetchall()

    def summary(self) -> dict:
        def one(sql: str, *args):
            return self.conn.execute(sql, args).fetchone()[0]
        runs = self.conn.execute(
            "select id, kind, source, status, stop_reason, new_rows, "
            "updated_rows from runs order by id desc limit 5").fetchall()
        return {
            "stat_rows": one("select count(*) from stat_observations"),
            "companies": one("select count(*) from companies"),
            "shipments": one("select count(*) from shipments"),
            "signals": one("select count(*) from signals"),
            "by_source": dict(self.conn.execute(
                "select source, count(*) from stat_observations "
                "group by source").fetchall()),
            "last_runs": [dict(r) for r in runs],
        }


def _utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

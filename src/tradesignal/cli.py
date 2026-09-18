"""CLI: doctor / collect / signals / import / status / export."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import __version__
from .config import load_env, load_spec
from .models import StatRow
from .signals import partner_share, yoy_growth
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "trade.db"

SOURCE_STATUS = {
    "comtrade": ("LIVE (preview)", "public/v1/preview работает без ключа; "
                 "rate limit ~1 запрос/мин; с ключом — полный data/v1/get"),
    "importyeti": ("BLOCKED", "technical: HTTP 403 Cloudflare (2026-09-17); обход запрещён"),
    "csvimport": ("LIVE_VERIFIED", "локальный импорт без сети"),
}


def _store(path) -> Store:
    return Store(Path(path) if path else DEFAULT_DB)


def cmd_doctor(args) -> int:
    print(f"trade-signal-collector {__version__}")
    env = load_env(ROOT)
    for code, (status, reason) in SOURCE_STATUS.items():
        print(f"{code}: {status} ({reason})")
    print(f"comtrade key: {'есть' if env.get('COMTRADE_API_KEY') else 'НЕТ — live недоступен'}")
    print(f"census key: {'есть' if env.get('CENSUS_API_KEY') else 'нет'}")
    if args.config:
        spec = load_spec(Path(args.config))
        errors = spec.validate()
        print(f"config: {args.config} — {'OK' if not errors else 'ОШИБКИ: ' + '; '.join(errors)}")
        print(f"запросов: {len(spec.queries)} (пилот: DEU/GBR/USA, HS 8422)")
    return 0


def cmd_collect(args) -> int:
    spec = load_spec(Path(args.config))
    errors = spec.validate()
    if errors:
        print("Ошибки конфигурации:", "; ".join(errors))
        return 2
    if args.dry_run:
        from .sources.comtrade import ComtradeConnector
        connector = ComtradeConnector("dry-run")
        for query in spec.queries:
            print(f"DRY-RUN {connector.code}: {connector.build_url(query)}")
        print("сетевых запросов не будет")
        return 0

    env = load_env(ROOT)
    from .sources.comtrade import ComtradeConnector
    key = env.get("COMTRADE_API_KEY", "").strip()
    if key:
        connector = ComtradeConnector(key, mode="data")
        mode_note = "data/v1/get с ключом"
    else:
        connector = ComtradeConnector(mode="preview")
        mode_note = ("public/v1/preview БЕЗ ключа: rate limit ~1 запрос/мин; "
                     "для полного канала вставь COMTRADE_API_KEY")
        print(f"ВНИМАНИЕ: {mode_note}")
    store = _store(args.db)
    try:
        run_id = store.start_run(
            "collect", json.dumps({"config": str(args.config),
                                   "mode": connector.mode}), connector.code)
        from .scheduler import run_queries
        reports = run_queries(spec, connector, store, run_id, ROOT / "data",
                              min_delay_seconds=0.0 if key else 65.0)
        ok = True
        for report in reports:
            print(f"{report.source}: {report.status} rows={report.rows} "
                  f"new={report.new} upd={report.updated} "
                  f"unchanged={report.unchanged}")
            if report.note:
                print(f"  {report.note}")
            if report.status in ("blocked", "failed"):
                ok = False
        store.finish_run(run_id, "completed" if ok else "partial")
        return 0 if ok else 2
    finally:
        store.close()


def cmd_signals(args) -> int:
    store = _store(args.db)
    try:
        from .models import SourceBlocked  # noqa: F401
        rows = [StatRow(
            source=r["source"], reporter_iso=r["reporter_iso"],
            partner_iso=r["partner_iso"], flow=r["flow"],
            hs_code=r["hs_code"], period=r["period"],
            value_usd=r["value_usd"], qty=r["qty"],
            qty_unit=r["qty_unit"]) for r in store.stat_rows()]
        if not rows:
            print("нет данных: сначала collect или import")
            return 2
        computed = yoy_growth(rows)
        if args.partner:
            computed += partner_share(rows, args.partner.upper())
        saved = 0
        for signal in computed:
            if signal.get("insufficient_history"):
                continue
            store.insert_signal(
                signal["kind"], signal["reporter_iso"], signal["partner_iso"],
                signal["hs_code"], signal["period"], signal["value_before"],
                signal["value_after"], signal["pct"], signal["hypothesis"])
            saved += 1
        print(f"сигналов сохранено: {saved} "
              f"(пропущено без истории: "
              f"{sum(1 for s in computed if s.get('insufficient_history'))})")
        for signal in computed[:10]:
            pct = signal.get("pct")
            tag = "insufficient" if signal.get("insufficient_history") else \
                  (f"{pct:+.1f}%" if pct is not None else "n/a")
            print(f"  {signal['kind']:14s} {signal['reporter_iso']} "
                  f"{signal['flow']} HS{signal['hs_code']} {signal['period']}: {tag}")
        return 0
    finally:
        store.close()


def cmd_import(args) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"файл не найден: {path}")
        return 2
    store = _store(args.db)
    try:
        run_id = store.start_run("import", json.dumps(
            {"file": str(path), "kind": args.kind}), f"import:{args.kind}")
        if args.kind == "stat":
            from .sources.csvimport import import_stat_csv
            rows = import_stat_csv(path)
            new = updated = unchanged = 0
            for row in rows:
                event = store.upsert_stat(row)
                new += event == "first_seen"
                updated += event == "updated"
                unchanged += event == "unchanged"
            print(f"импорт статистики: строк={len(rows)} new={new} "
                  f"upd={updated} unchanged={unchanged}")
        elif args.kind == "companies":
            from .sources.csvimport import import_companies_csv
            records = import_companies_csv(path)
            for record in records:
                store.upsert_company(record)
            print(f"импорт компаний: {len(records)}")
        elif args.kind == "shipments":
            from .sources.csvimport import import_shipments_csv
            companies = {r["source_key"]: r["id"] for r in store.conn.execute(
                "select source_key, id from companies").fetchall()}
            shipments = import_shipments_csv(path, companies)
            for shipment in shipments:
                store.insert_shipment(**shipment)
            ff = sum(1 for s in shipments if s["ff_suspect"])
            print(f"импорт поставок: {len(shipments)} (ff_suspect: {ff})")
        store.finish_run(run_id, "completed", rows=len(rows) if args.kind == "stat" else 0)
        return 0
    finally:
        store.close()


def cmd_status(args) -> int:
    store = _store(args.db)
    try:
        info = store.summary()
        print(f"рядов статистики: {info['stat_rows']}  по источникам: {info['by_source']}")
        print(f"компаний: {info['companies']}  поставок: {info['shipments']}  "
              f"сигналов: {info['signals']}")
        for run in info["last_runs"]:
            print(f"  run#{run['id']} {run['kind']:8s} {run['source'] or '-':20s} "
                  f"{run['status']:10s} new={run['new_rows']} upd={run['updated_rows']}")
    finally:
        store.close()
    return 0


def cmd_export(args) -> int:
    from .export import (export_jsonl, export_signals_csv, export_shipments_csv,
                         export_stat_csv)
    store = _store(args.db)
    out = Path(args.out)
    try:
        if args.kind == "stat":
            written = export_stat_csv(store.stat_rows(), out)
        elif args.kind == "signals":
            written = export_signals_csv(store.signals(), out)
        elif args.kind == "shipments":
            rows = store.conn.execute(
                "select c.source as company_source, c.source_key as company_key, "
                "c.name as company_name, s.supplier_name, s.supplier_country, "
                "s.arrival_date, s.port, s.hs_codes, s.weight_kg_declared, "
                "s.quantity_declared, s.ff_suspect from shipments s "
                "join companies c on c.id = s.company_id").fetchall()
            written = export_shipments_csv(rows, out)
        else:
            written = export_jsonl(store.stat_rows(), out)
        print(f"экспортировано {written} строк → {out}")
    finally:
        store.close()
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="tradesignal")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor")
    p.add_argument("--config")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("collect")
    p.add_argument("--config", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("signals")
    p.add_argument("--partner", help="ISO3 партнёра для доли (напр. CHN)")
    p.set_defaults(func=cmd_signals)

    p = sub.add_parser("import")
    p.add_argument("--kind", required=True,
                   choices=["stat", "companies", "shipments"])
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("export")
    p.add_argument("--kind", default="stat",
                   choices=["stat", "signals", "shipments", "jsonl"])
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

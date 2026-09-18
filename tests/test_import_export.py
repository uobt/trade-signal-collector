"""Тесты CSV-импорта (контуры A и B) и экспорта."""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tradesignal.export import export_stat_csv
from tradesignal.models import CompanyRecord
from tradesignal.sources.csvimport import (import_companies_csv,
                                           import_shipments_csv,
                                           import_stat_csv, normalize_name)
from tradesignal.storage import Store

EX = Path(__file__).resolve().parent.parent / "examples"


class TestStatImport(unittest.TestCase):
    def test_demo_csv(self):
        rows = import_stat_csv(EX / "demo_stat_import.csv", "demo-import")
        self.assertEqual(len(rows), 8)
        usa = [r for r in rows if r.reporter_iso == "USA"]
        self.assertEqual(len(usa), 4)   # World + CHN × 2 года
        self.assertEqual(rows[0].partner_iso, "WLD")   # numeric → ISO3

    def test_rows_are_valid_statrows(self):
        for row in import_stat_csv(EX / "demo_stat_import.csv", "demo-import"):
            self.assertTrue(row.hs_code and row.period)
            self.assertIn(row.flow, ("M", "X"))


class TestCompaniesImport(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_name("Nordwind Verpackungen GmbH"),
                         "nordwind verpackungen")
        self.assertEqual(normalize_name("Harborline Packaging Ltd"),
                         "harborline packaging")

    def test_import(self):
        records = import_companies_csv(EX / "demo_companies_import.csv")
        self.assertEqual(len(records), 3)
        names = {r.name_norm for r in records}
        self.assertIn("expeditors international of washington", names)


class TestShipmentsImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        for record in import_companies_csv(EX / "demo_companies_import.csv"):
            self.store.upsert_company(record)
        self.companies = {r["source_key"]: r["id"] for r in
                          self.store.conn.execute(
                              "select source_key, id from companies").fetchall()}

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_shipments_and_ff_flag(self):
        shipments = import_shipments_csv(
            EX / "demo_shipments_import.csv", self.companies)
        self.assertEqual(len(shipments), 6)
        ff = [s for s in shipments if s["ff_suspect"]]
        # imp-003 — сам экспедитор: его «поставки» помечены шумом
        self.assertTrue(all(s["company_id"] == self.companies["imp-003"]
                            for s in ff))

    def test_idempotent_insert(self):
        shipments = import_shipments_csv(
            EX / "demo_shipments_import.csv", self.companies)
        for shipment in shipments:
            self.assertEqual(self.store.insert_shipment(**shipment), "first_seen")
        for shipment in shipments:
            self.assertEqual(self.store.insert_shipment(**shipment), "unchanged")
        count = self.store.conn.execute(
            "select count(*) from shipments").fetchone()[0]
        self.assertEqual(count, 6)


class TestExport(unittest.TestCase):
    def test_csv_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "stat.csv"
            written = export_stat_csv([
                {"source": "s", "reporter_iso": "DEU", "partner_iso": "WLD",
                 "flow": "M", "hs_code": "8422", "hs_length": 4,
                 "period": "2024", "value_usd": 1.0, "qty": None,
                 "qty_unit": "kg", "observed_at": "2026-09-17"}], out)
            self.assertEqual(written, 1)
            raw = out.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            with out.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0][0], "source")
            self.assertEqual(rows[1][6], "2024")   # колонка period


if __name__ == "__main__":
    unittest.main()

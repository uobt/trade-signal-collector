"""Тесты: парсер Comtrade, дедуп рядов, история расхождений, сигналы."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tradesignal.models import (RawDocument, StatRow, TradeQuery,
                                forwarder_suspect)
from tradesignal.signals import partner_share, yoy_growth
from tradesignal.sources.comtrade import ComtradeConnector, numeric
from tradesignal.storage import Store

FIX = Path(__file__).parent / "fixtures"


def replace_periods(query: TradeQuery, periods: list[str]) -> TradeQuery:
    from dataclasses import replace
    return replace(query, periods=periods)


class TestComtradeParser(unittest.TestCase):
    def setUp(self):
        self.connector = ComtradeConnector("test-key")
        self.doc = RawDocument(
            url="https://comtradeapi.un.org/data/v1/get/C/A/HS?x=1",
            status=200,
            content=(FIX / "comtrade_de_8422.json").read_text(encoding="utf-8"))
        self.page = self.connector.parse_response(self.doc)

    def test_total_lines_only_no_double_count(self):
        """Preview отдаёт total-строки И их разбивки: парсер берёт только
        total, наивная сумма давала бы двойной счёт."""
        self.assertEqual(len(self.page.rows), 4)
        for row in self.page.rows:
            if (row.partner_iso == "WLD" and row.period == "2024"):
                self.assertEqual(row.value_usd, 1780000000.0)  # не 1780+700
            if (row.partner_iso == "CHN" and row.period == "2024"):
                self.assertEqual(row.value_usd, 790000000.0)   # не 790+710+80
        self.assertEqual(self.page.status, "success")

    def test_rows_and_uniqueness(self):
        keys = {row.key() for row in self.page.rows}
        self.assertEqual(len(keys), 4)

    def test_numeric_to_iso3(self):
        de = [r for r in self.page.rows if r.reporter_iso == "DEU"]
        self.assertEqual(len(de), 4)
        world = [r for r in self.page.rows if r.partner_iso == "WLD"]
        self.assertEqual(len(world), 2)
        china = [r for r in self.page.rows if r.partner_iso == "CHN"]
        self.assertEqual(len(china), 2)

    def test_values_preserved(self):
        row = next(r for r in self.page.rows if r.period == "2024"
                   and r.partner_iso == "WLD")
        self.assertEqual(row.value_usd, 1780000000.0)
        self.assertEqual(row.qty, 112000.0)
        self.assertEqual(row.qty_unit, "kg")
        self.assertEqual(row.hs_length, 4)

    def test_invalid_json_is_failed_not_crash(self):
        bad = RawDocument(url="x", status=200, content="not json")
        page = self.connector.parse_response(bad)
        self.assertEqual((page.status, page.stop_reason),
                         ("failed", "invalid_json"))

    def test_empty_data(self):
        empty = RawDocument(url="x", status=200, content=json.dumps({"data": []}))
        page = self.connector.parse_response(empty)
        self.assertEqual(page.status, "success")
        self.assertEqual(page.stop_reason, "exhausted")

    def test_url_builder(self):
        query = TradeQuery(reporter="DEU", partner="0", flow="M",
                           hs="8422", periods=["2023", "2024"])
        url = self.connector.build_url(query)
        self.assertIn("reporterCode=276", url)
        self.assertIn("cmdCode=8422", url)
        self.assertIn("flowCode=M", url)
        self.assertIn("period=2023%2C2024", url)

    def test_preview_period_limits(self):
        self.assertEqual(ComtradeConnector(mode="preview").max_periods, 1)
        self.assertEqual(ComtradeConnector("k").max_periods, 20)
        query = TradeQuery(reporter="DEU", partner="0", flow="M",
                           hs="8422", periods=["2023", "2024"])
        self.assertNotIn(",", ComtradeConnector(mode="preview").build_url(
            replace_periods(query, ["2023"])))

    def test_numeric_unknown_raises(self):
        with self.assertRaises(ValueError):
            numeric("XXX")


class TestValidation(unittest.TestCase):
    def test_flow_and_hs(self):
        errors = TradeQuery(reporter="DEU", partner="0", flow="Z",
                            hs="842", periods=["2024"]).validate()
        self.assertTrue(any("flow" in e for e in errors))
        self.assertTrue(any("hs" in e for e in errors))

    def test_period_forms(self):
        ok = TradeQuery(reporter="DEU", partner="0", flow="M", hs="84",
                        periods=["2024-08"])
        self.assertEqual(ok.validate(), [])
        bad = TradeQuery(reporter="DEU", partner="0", flow="M", hs="84",
                         periods=["2024081"])
        self.assertTrue(bad.validate())


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_upsert_dedup_same_key(self):
        row = StatRow(source="s", reporter_iso="DEU", partner_iso="WLD",
                      flow="M", hs_code="8422", period="2024",
                      value_usd=100.0)
        self.assertEqual(self.store.upsert_stat(row), "first_seen")
        self.assertEqual(self.store.upsert_stat(row), "unchanged")

    def test_value_change_goes_to_history(self):
        first = StatRow(source="s", reporter_iso="DEU", partner_iso="WLD",
                        flow="M", hs_code="8422", period="2024",
                        value_usd=100.0)
        self.store.upsert_stat(first)
        revised = StatRow(source="s", reporter_iso="DEU", partner_iso="WLD",
                          flow="M", hs_code="8422", period="2024",
                          value_usd=110.0)
        self.assertEqual(self.store.upsert_stat(revised), "updated")
        current = self.store.stat_rows()[0]
        self.assertEqual(current["value_usd"], 110.0)
        history = self.store.conn.execute(
            "select count(*) from stat_history").fetchone()[0]
        self.assertEqual(history, 1)

    def test_disappearance_keeps_row(self):
        row = StatRow(source="s", reporter_iso="USA", partner_iso="WLD",
                      flow="M", hs_code="8422", period="2023",
                      value_usd=1.0)
        self.store.upsert_stat(row)
        # следующий прогон не вернул этот ряд — он остаётся в базе
        self.assertEqual(self.store.stat_rows()[0]["period"], "2023")


class TestSignals(unittest.TestCase):
    def rows(self):
        return [
            StatRow(source="s", reporter_iso="DEU", partner_iso="WLD",
                    flow="M", hs_code="8422", period="2023", value_usd=100.0),
            StatRow(source="s", reporter_iso="DEU", partner_iso="WLD",
                    flow="M", hs_code="8422", period="2024", value_usd=130.0),
            StatRow(source="s", reporter_iso="DEU", partner_iso="CHN",
                    flow="M", hs_code="8422", period="2023", value_usd=40.0),
            StatRow(source="s", reporter_iso="DEU", partner_iso="CHN",
                    flow="M", hs_code="8422", period="2024", value_usd=60.0),
        ]

    def test_yoy(self):
        growth = {g["partner_iso"]: g for g in yoy_growth(self.rows())}
        self.assertAlmostEqual(growth["WLD"]["pct"], 30.0)
        self.assertAlmostEqual(growth["CHN"]["pct"], 50.0)
        self.assertTrue(growth["WLD"]["hypothesis"])

    def test_yoy_zero_base_is_none_not_crash(self):
        rows = self.rows() + [
            StatRow(source="s", reporter_iso="ITA", partner_iso="WLD",
                    flow="M", hs_code="8422", period="2023", value_usd=0.0),
            StatRow(source="s", reporter_iso="ITA", partner_iso="WLD",
                    flow="M", hs_code="8422", period="2024", value_usd=5.0)]
        for growth in yoy_growth(rows):
            if growth["reporter_iso"] == "ITA":
                self.assertIsNone(growth["pct"])

    def test_insufficient_history(self):
        rows = [StatRow(source="s", reporter_iso="FRA", partner_iso="WLD",
                        flow="M", hs_code="8422", period="2024",
                        value_usd=10.0)]
        growth = yoy_growth(rows)
        self.assertEqual(len(growth), 1)
        self.assertTrue(growth[0]["insufficient_history"])

    def test_partner_share(self):
        share = partner_share(self.rows(), "CHN")
        self.assertEqual(len(share), 2)
        self.assertEqual(share[1]["pct"], round(60.0 / 130.0 * 100, 1))

    def test_hs_levels_not_mixed(self):
        rows = self.rows() + [
            StatRow(source="s", reporter_iso="DEU", partner_iso="WLD",
                    flow="M", hs_code="84", period="2023", value_usd=999.0)]
        growth = yoy_growth(rows)
        hs84 = [g for g in growth if g["hs_code"] == "84"]
        self.assertTrue(all(g["insufficient_history"] for g in hs84))


class TestImports(unittest.TestCase):
    """Smoke: все модули, включая транспорт, импортируются без сети."""

    def test_all_modules_importable(self):
        import tradesignal.cli  # noqa: F401
        import tradesignal.scheduler  # noqa: F401
        import tradesignal.transports.http  # noqa: F401


class TestForwarderNoise(unittest.TestCase):
    def test_known_ff(self):
        self.assertTrue(forwarder_suspect("Expeditors International of Washington"))
        self.assertTrue(forwarder_suspect("Kuehne+Nagel"))
        self.assertTrue(forwarder_suspect("DSV Air & Sea"))

    def test_real_buyer_not_flagged(self):
        self.assertFalse(forwarder_suspect("Nordwind Verpackungen GmbH"))
        self.assertFalse(forwarder_suspect("Harborline Packaging Ltd"))


if __name__ == "__main__":
    unittest.main()

"""Быстрый просмотр живых рядов comtrade-preview в БД."""
import sqlite3

conn = sqlite3.connect("data/trade.db")
rows = conn.execute(
    "select reporter_iso, partner_iso, hs_code, period, value_usd "
    "from stat_observations where source='comtrade-preview' "
    "order by reporter_iso, period").fetchall()
for reporter, partner, hs, period, value in rows:
    print(f"{reporter} {partner} HS{hs} {period}: ${value:,.0f}")
conn.close()

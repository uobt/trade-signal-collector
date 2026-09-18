"""Перекрёстная сверка каналов: comtrade (ключ) vs comtrade-preview."""
import sqlite3

conn = sqlite3.connect("data/trade.db")
rows = conn.execute(
    "select reporter_iso, partner_iso, hs_code, period, value_usd, source "
    "from stat_observations where source in ('comtrade', 'comtrade-preview')"
).fetchall()
by_key = {}
for reporter, partner, hs, period, value, source in rows:
    by_key.setdefault((reporter, partner, hs, period), {})[source] = value

match = diff = only = 0
for key, sources in sorted(by_key.items()):
    if len(sources) < 2:
        only += 1
        print(f"только один канал: {key} -> {list(sources)}")
        continue
    a, b = sources.get("comtrade"), sources.get("comtrade-preview")
    if a is not None and b is not None and abs(a - b) <= max(1.0, 1e-9 * max(abs(a), abs(b))):
        match += 1
    else:
        diff += 1
        print(f"РАСХОЖДЕНИЕ {key}: data={a} preview={b}")
print(f"\nсовпало: {match}, расхождений: {diff}, только один канал: {only}")
conn.close()

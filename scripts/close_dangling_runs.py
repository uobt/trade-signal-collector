import sqlite3

conn = sqlite3.connect("data/trade.db")
conn.execute(
    "update runs set status='failed', note='import error: transports', "
    "finished_at=datetime('now') where status='running'")
conn.commit()
print("закрыто зависших прогонов:", conn.total_changes)
conn.close()

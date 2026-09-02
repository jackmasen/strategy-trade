# -*- coding: utf-8 -*-
"""SQLite迁移：为strategy_configs表添加strategy_type列"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime", "app.db")
print(f"DB: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

cols = [row[1] for row in c.execute("PRAGMA table_info(strategy_configs)").fetchall()]
print(f"Current columns: {cols}")

if "strategy_type" not in cols:
    c.execute("ALTER TABLE strategy_configs ADD COLUMN strategy_type VARCHAR(32) DEFAULT 'standard'")
    conn.commit()
    print("[OK] Added 'strategy_type' column")
else:
    print("[SKIP] 'strategy_type' column already exists")

cols2 = [row[1] for row in c.execute("PRAGMA table_info(strategy_configs)").fetchall()]
print(f"Updated columns: {cols2}")
conn.close()

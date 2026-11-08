"""Reseed the products table from the current catalog.json so DB ids match the
frontend's product ids exactly. Orders are left untouched."""
import json
import sqlite3
from pathlib import Path

import store_db

DB = Path(__file__).with_name("cpshop.db")
CAT = Path(__file__).with_name("catalog.json")

with sqlite3.connect(DB) as conn:
    before = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    order_items = conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
    conn.execute("DELETE FROM products")
    conn.commit()
    print(f"cleared {before} products (kept {order_items} order_items)")

store_db.init_db(seed=True)

raw = json.loads(CAT.read_text(encoding="utf-8"))
expected = {p["id"] for p in raw["products"]}

with sqlite3.connect(DB) as conn:
    after = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    ids = {r[0] for r in conn.execute("SELECT id FROM products")}
    missing = expected - ids
    extra = ids - expected
    print(f"reseeded: {after} products (catalog says {len(expected)})")
    print(f"missing from DB: {len(missing)}  extra in DB: {len(extra)}")
    for pid in ("codm-015", "premium-001", "gift-steam-100"):
        r = conn.execute("SELECT id, game, title, price FROM products WHERE id=?", (pid,)).fetchone()
        print(f"  {pid:16s}", "OK" if r else "MISSING", r)

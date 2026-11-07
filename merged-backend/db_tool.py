#!/usr/bin/env python3
"""db_tool — small CLI to inspect/reset the CP.Shop backend SQLite DB."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import store_db

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "cpshop.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def cmd_stats() -> None:
    conn = _connect()
    tables = ["products", "customers", "orders", "order_items"]
    out: dict[str, int] = {}
    with conn:
        for t in tables:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
            except sqlite3.OperationalError:
                out[t] = -1
    # stable output order
    print("db_path:", str(DB_PATH))
    for k in tables:
        print(f"{k}: {out[k]}")
    # also useful rollups if orders exist
    with conn:
        try:
            paid = conn.execute("SELECT COUNT(*) AS c FROM orders WHERE status='paid'").fetchone()["c"]
            revenue = conn.execute(
                "SELECT COALESCE(SUM(total),0) AS s FROM orders WHERE status='paid'"
            ).fetchone()["s"]
            print("paid_orders:", paid)
            print("paid_total_toman:", revenue)
        except sqlite3.OperationalError:
            pass


def cmd_reset() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    store_db.init_db(seed=True)
    print("reset_ok")


def cmd_export() -> None:
    out_path = HERE / "db_backup_orders.json"
    # store_db provides the actual export implementation.
    store_db.export_orders_json(out_path)
    print("export_ok:", str(out_path))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    sub.add_parser("reset")
    sub.add_parser("export")
    args = parser.parse_args()

    if args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "reset":
        cmd_reset()
    elif args.cmd == "export":
        cmd_export()
    else:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

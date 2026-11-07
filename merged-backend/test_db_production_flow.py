#!/usr/bin/env python3
"""Verify DB production flow end-to-end.

Runs:
1) fresh DB init + seed count
2) create_order(customer + player_id per item)
3) pay_order
4) get_order and print full record
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import store_db


def main() -> None:
    # fresh DB
    if store_db.DB_PATH.exists():
        store_db.DB_PATH.unlink()

    store_db.init_db(seed=True)

    with sqlite3.connect(store_db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        products_count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]

    print("seeded_products:", products_count)

    order = store_db.create_order(
        items=[
            {"product_id": "codm-80", "quantity": 2, "player_id": "12345678"},
        ],
        customer_name="Ali",
        customer_contact="+98912-345-6789",
    )
    print("created_order:", order)

    paid = store_db.pay_order(order["tracking"], order["pay_token"])
    print("paid_order:", paid)

    got = store_db.get_order(order["tracking"])
    print("get_order_full_record:\n", got)

    assert got is not None
    assert got["status"] == "paid"
    assert got["customer_name"] == "Ali"
    assert got["items"][0]["player_id"] == "12345678"


if __name__ == "__main__":
    main()

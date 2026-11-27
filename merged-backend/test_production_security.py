#!/usr/bin/env python3
"""Production DB + security regression test for the CP.Shop backend.

37 assertions across:
  1. fresh reset + catalog seed (idempotent)
  2. schema constraints (FK, NOT NULL, CHECK, indexes)
  3. order lifecycle: create -> pay -> read, with customer + player_id
  4. privacy: contact masked without token, full with token
  5. token gate: wrong token cannot pay or read details
  6. stock decrement on payment
  7. backup export (raw + redacted)
  8. price tampering is impossible (server-side pricing)
  9. total mismatch rejected (claimed_total must equal the line sum)
 10. pay token stored as a hash, never raw
 11. pay token is single-use
 12. pay token expiry enforced
 13. idempotent gateway retry

Run: python test_production_security.py
Exit code 0 == all assertions passed.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import store_db

FAILED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        FAILED.append(label)


def main() -> int:
    print("=" * 70)
    print("1. FRESH RESET + SEED")
    print("=" * 70)
    if store_db.DB_PATH.exists():
        store_db.DB_PATH.unlink()
    store_db.init_db(seed=True)

    with sqlite3.connect(store_db.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        n = c.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    catalog = json.loads(store_db.CATALOG_PATH.read_text(encoding="utf-8"))
    expected = len(catalog["products"])
    print(f"  seeded products: {n} (catalog has {expected})")
    check("seed count matches catalog", n == expected, f"{n} != {expected}")

    # idempotency: run again, count must not change
    store_db.init_db(seed=True)
    with sqlite3.connect(store_db.DB_PATH) as c:
        n2 = c.execute("SELECT COUNT(*) c FROM products").fetchone()[0]
    check("re-seed is idempotent", n2 == n, f"{n2} != {n}")

    print()
    print("=" * 70)
    print("2. SCHEMA CONSTRAINTS")
    print("=" * 70)
    with sqlite3.connect(store_db.DB_PATH) as c:
        pcols = {r[1] for r in c.execute("PRAGMA table_info(products)")}
        ocols = {r[1] for r in c.execute("PRAGMA table_info(orders)")}
        icols = {r[1] for r in c.execute("PRAGMA table_info(order_items)")}
        idx = {r[1] for r in c.execute("PRAGMA index_list(orders)")}
        idx |= {r[1] for r in c.execute("PRAGMA index_list(order_items)")}
        fks = c.execute("PRAGMA foreign_key_list(order_items)").fetchall()

    check("products has stock/is_active/currency/created_at",
          {"stock", "is_active", "currency", "created_at"} <= pcols)
    check("orders has customer_name/customer_contact",
          {"customer_name", "customer_contact"} <= ocols)
    check("order_items has player_id", "player_id" in icols)
    check("orders.tracking indexed", "idx_orders_tracking" in idx)
    check("order_items.order_id indexed", "idx_order_items_order_id" in idx)
    check("order_items has 2 foreign keys", len(fks) == 2, str(fks))

    # FK must actually reject an orphan item
    fk_enforced = False
    try:
        with sqlite3.connect(store_db.DB_PATH) as c:
            c.execute("PRAGMA foreign_keys=ON")
            c.execute(
                "INSERT INTO order_items(order_id,product_id,title,game,quantity,unit_price,player_id)"
                " VALUES(999999,'no-such-product','x','x',1,1000,'1234')"
            )
            c.commit()
    except sqlite3.IntegrityError:
        fk_enforced = True
    check("FK rejects orphan order_item", fk_enforced)

    print()
    print("=" * 70)
    print("3. ORDER LIFECYCLE (customer + player_id)")
    print("=" * 70)
    with sqlite3.connect(store_db.DB_PATH) as c:
        row = c.execute(
            "SELECT id, title, price FROM products WHERE category='codm' LIMIT 1"
        ).fetchone()
    pid, ptitle, pprice = row
    print(f"  using product: {pid} / {ptitle} / {pprice}")

    order = store_db.create_order(
        items=[{"product_id": pid, "quantity": 2, "player_id": "12345678"}],
        customer_name="Ali Rezaei",
        customer_contact="09121234567",
    )
    print(f"  created: {order['tracking']} total={order['total']}")
    check("total is server-priced", order["total"] == pprice * 2,
          f"{order['total']} != {pprice * 2}")
    check("status is pending", order["status"] == "pending")
    check("pay_token issued", bool(order.get("pay_token")))

    paid = store_db.pay_order(order["tracking"], order["pay_token"])
    print(f"  paid: {paid}")
    check("status became paid", paid["status"] == "paid")

    print()
    print("=" * 70)
    print("4. PRIVACY — contact masked without token")
    print("=" * 70)
    anon = store_db.get_order(order["tracking"])
    owned = store_db.get_order(order["tracking"], order["pay_token"])
    print(f"  anonymous contact : {anon['customer_contact']}")
    print(f"  owner contact     : {owned['customer_contact']}")
    check("anonymous name hidden", anon["customer_name"] is None)
    check("anonymous contact masked", "*" in (anon["customer_contact"] or ""))
    check("owner sees full contact", owned["customer_contact"] == "09121234567")
    check("owner sees name", owned["customer_name"] == "Ali Rezaei")
    check("player_id preserved", owned["items"][0]["player_id"] == "12345678")

    print()
    print("=" * 70)
    print("5. TOKEN GATE")
    print("=" * 70)
    second = store_db.create_order(
        items=[{"product_id": pid, "quantity": 1, "player_id": "87654321"}],
        customer_name="Sara",
        customer_contact="@sara_tg",
    )
    blocked = False
    try:
        store_db.pay_order(second["tracking"], "wrong-token-value")
    except store_db.OrderError as e:
        blocked = "توکن" in str(e)
    check("wrong token cannot pay", blocked)

    anon2 = store_db.get_order(second["tracking"], "wrong-token-value")
    check("wrong token cannot unmask contact",
          anon2["customer_contact"] != "@sara_tg")

    print()
    print("=" * 70)
    print("6. STOCK DECREMENT")
    print("=" * 70)
    with sqlite3.connect(store_db.DB_PATH) as c:
        before = c.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()[0]
    store_db.pay_order(second["tracking"], second["pay_token"])
    with sqlite3.connect(store_db.DB_PATH) as c:
        after = c.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()[0]
    print(f"  stock {before} -> {after}")
    check("stock decremented by quantity", after == before - 1)

    print()
    print("=" * 70)
    print("7. BACKUP EXPORT (raw + redacted)")
    print("=" * 70)
    raw_path = Path("_test_backup_raw.json")
    red_path = Path("_test_backup_redacted.json")
    n_raw = store_db.export_orders_json(raw_path)
    n_red = store_db.export_orders_json(red_path, redact=True)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    red = json.loads(red_path.read_text(encoding="utf-8"))
    print(f"  exported {n_raw} orders (raw) / {n_red} (redacted)")
    check("raw export contains real contact",
          any(o["customer_contact"] == "09121234567" for o in raw["orders"]))
    check("redacted export hides contact",
          all("*" in (o["customer_contact"] or "*") for o in red["orders"]))
    raw_path.unlink()
    red_path.unlink()

    print()
    print("=" * 70)
    print("8. PRICE TAMPERING IMPOSSIBLE")
    print("=" * 70)
    tampered = store_db.create_order(
        items=[{"product_id": pid, "quantity": 1, "player_id": "12345678",
                "price": 1, "unit_price": 1, "total": 1}],
        customer_name="Hacker",
        customer_contact="09120000000",
    )
    check("client price ignored", tampered["total"] == pprice,
          f"{tampered['total']} != {pprice}")

    print()
    print("=" * 70)
    print("9. TOTAL MISMATCH REJECTED")
    print("=" * 70)
    # correct total accepted
    ok_order = store_db.create_order(
        items=[{"product_id": pid, "quantity": 2, "player_id": "12345678"}],
        customer_name="Total Check",
        customer_contact="09120000002",
        claimed_total=pprice * 2,
    )
    check("matching claimed_total accepted", ok_order["total"] == pprice * 2)

    # wrong total rejected
    rejected = False
    detail = ""
    try:
        store_db.create_order(
            items=[{"product_id": pid, "quantity": 2, "player_id": "12345678"}],
            customer_name="Total Check",
            customer_contact="09120000002",
            claimed_total=1,
        )
    except store_db.OrderError as e:
        rejected = True
        detail = str(e)
    check("mismatched claimed_total rejected", rejected, detail)
    print(f"  rejection message: {detail}")

    # non-numeric total rejected
    rejected2 = False
    try:
        store_db.create_order(
            items=[{"product_id": pid, "quantity": 1, "player_id": "12345678"}],
            customer_name="Total Check",
            customer_contact="09120000002",
            claimed_total="abc",
        )
    except store_db.OrderError:
        rejected2 = True
    check("non-numeric claimed_total rejected", rejected2)

    print()
    print("=" * 70)
    print("10. TOKEN STORED AS HASH, NOT RAW")
    print("=" * 70)
    tok_order = store_db.create_order(
        items=[{"product_id": pid, "quantity": 1, "player_id": "12345678"}],
        customer_name="Hash Check",
        customer_contact="09120000003",
    )
    raw_tok = tok_order["pay_token"]
    with sqlite3.connect(store_db.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        db_row = c.execute(
            "SELECT pay_token_hash, pay_token_expires_at, pay_token_used_at"
            "  FROM orders WHERE tracking = ?", (tok_order["tracking"],)
        ).fetchone()
        # raw token must not appear anywhere in the orders table
        raw_hits = c.execute(
            "SELECT COUNT(*) FROM orders WHERE pay_token_hash = ?", (raw_tok,)
        ).fetchone()[0]
    print(f"  stored hash: {db_row['pay_token_hash'][:24]}…")
    print(f"  expires_at : {db_row['pay_token_expires_at']}")
    check("raw token not stored", raw_hits == 0)
    check("hash is sha256 hex", len(db_row["pay_token_hash"]) == 64)
    check("hash matches raw token",
          db_row["pay_token_hash"] == store_db.hash_token(raw_tok))
    check("expiry recorded", bool(db_row["pay_token_expires_at"]))
    check("not yet used", db_row["pay_token_used_at"] is None)

    print()
    print("=" * 70)
    print("11. TOKEN IS SINGLE-USE")
    print("=" * 70)
    store_db.pay_order(tok_order["tracking"], raw_tok)
    with sqlite3.connect(store_db.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        used = c.execute(
            "SELECT pay_token_used_at FROM orders WHERE tracking = ?",
            (tok_order["tracking"],)
        ).fetchone()["pay_token_used_at"]
    check("token marked used after payment", bool(used))

    # replaying the burned token on a NEW order must fail
    other = store_db.create_order(
        items=[{"product_id": pid, "quantity": 1, "player_id": "12345678"}],
        customer_name="Replay Check",
        customer_contact="09120000004",
    )
    replay_blocked = False
    try:
        store_db.pay_order(other["tracking"], raw_tok)
    except store_db.OrderError:
        replay_blocked = True
    check("burned token cannot pay another order", replay_blocked)

    # a burned token cannot be reused to cancel either
    cancel_blocked = False
    try:
        store_db.cancel_order(other["tracking"], raw_tok)
    except store_db.OrderError:
        cancel_blocked = True
    check("burned token cannot cancel", cancel_blocked)

    print()
    print("=" * 70)
    print("12. TOKEN EXPIRY")
    print("=" * 70)
    exp_order = store_db.create_order(
        items=[{"product_id": pid, "quantity": 1, "player_id": "12345678"}],
        customer_name="Expiry Check",
        customer_contact="09120000005",
    )
    # backdate the expiry to simulate a stale token
    with sqlite3.connect(store_db.DB_PATH) as c:
        c.execute(
            "UPDATE orders SET pay_token_expires_at = ? WHERE tracking = ?",
            ("2020-01-01 00:00:00", exp_order["tracking"]),
        )
        c.commit()
    expired_blocked = False
    detail = ""
    try:
        store_db.pay_order(exp_order["tracking"], exp_order["pay_token"])
    except store_db.OrderError as e:
        expired_blocked = True
        detail = str(e)
    check("expired token rejected", expired_blocked, detail)
    print(f"  rejection message: {detail}")

    print()
    print("=" * 70)
    print("13. IDEMPOTENT GATEWAY RETRY")
    print("=" * 70)
    # the token that actually paid an order may be replayed to that same order
    again = store_db.pay_order(tok_order["tracking"], raw_tok)
    check("same token re-confirms its own paid order", again["status"] == "paid")

    print()
    print("=" * 70)
    if FAILED:
        print(f"RESULT: {len(FAILED)} FAILED")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    print(f"final stats: {store_db.db_stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

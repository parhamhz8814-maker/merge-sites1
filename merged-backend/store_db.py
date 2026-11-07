#!/usr/bin/env python3
"""
store_db — SQLite persistence for CP.Shop.

Two concerns, one module:

  1. PRODUCTS   seeded from catalog.json (id → canonical server-side price).
                Clients never set prices; orders are priced ONLY from this table.
  2. ORDERS     order + order_items rows with a strict lifecycle:
                pending → paid   (cancel allowed only while pending)

Connection policy: one connection per operation (SQLite handles concurrent
readers; writes are short). WAL mode for reader/writer overlap.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "cpshop.db"
CATALOG_PATH = HERE / "catalog.json"

MAX_ITEMS = 30
MAX_QTY = 99
# player ids: letters (any language), digits, and the separators games actually use
_PLAYER_ID_RE = re.compile(r"^[\w\- .@#]{1,40}$", re.UNICODE)
_TRACKING_RE = re.compile(r"^CPS-[A-Z0-9]{8}$")

_SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS products(
    id        TEXT PRIMARY KEY,
    game_key  TEXT NOT NULL,
    game      TEXT NOT NULL,
    title     TEXT NOT NULL,
    category  TEXT NOT NULL,
    price     INTEGER NOT NULL CHECK(price > 0),
    old_price INTEGER,
    badge     TEXT
);


-- Stores customer/contact details collected from the checkout form.
-- Orders can optionally link to a customer when you add that wiring.
CREATE TABLE IF NOT EXISTS customers(
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    phone             TEXT,
    email             TEXT,
    game_player_id   TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(email),
    UNIQUE(phone),
    UNIQUE(game_player_id)
);

CREATE TABLE IF NOT EXISTS orders(
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking     TEXT UNIQUE NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                  CHECK(status IN ('pending','paid','canceled')),
    customer_id  INTEGER REFERENCES customers(id)
                  ON DELETE SET NULL,
    total        INTEGER NOT NULL CHECK(total > 0),
    item_count   INTEGER NOT NULL CHECK(item_count > 0),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at      TEXT,
    pay_token    TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);

CREATE TABLE IF NOT EXISTS order_items(
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id   TEXT NOT NULL,
    title        TEXT NOT NULL,
    game         TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99),
    unit_price   INTEGER NOT NULL CHECK(unit_price > 0),
    player_id    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_order_items_player ON order_items(player_id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(seed: bool = True) -> None:
    """Create schema idempotently and optionally seed products.

    Seeding is idempotent: it inserts products from catalog.json only when the
    products table is empty.
    """
    with _connect() as conn:
        conn.executescript(_SCHEMA)

        # migration for databases created before schema wiring
        # - orders.customer_id might not exist in older DBs
        cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
        if "pay_token" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN pay_token TEXT")
        if "customer_id" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN customer_id INTEGER")


        # migration: ensure order_items has player_id
        oi_cols = {r[1] for r in conn.execute("PRAGMA table_info(order_items)")}
        if "player_id" not in oi_cols:
            conn.execute("ALTER TABLE order_items ADD COLUMN player_id TEXT NOT NULL DEFAULT ''")

        # migration: ensure customers table exists (minimal)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS customers("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL,"
            " phone TEXT,"
            " email TEXT,"
            " game_player_id TEXT,"
            " created_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )

        # seed products idempotently (INSERT OR REPLACE by primary key)
        if seed:
            raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            games = raw["games"]
            game_names = {
                (k if isinstance(g, str) else g.get("key", k)): (g if isinstance(g, str) else g)
                for k, g in (games.items() if isinstance(games, dict) else
                             [(g.get("key", ""), g) for g in games])
            }
            rows = []
            for p in raw["products"]:
                g = game_names.get(p["gameKey"], {})
                fa = g.get("fa", p["game"]) if isinstance(g, dict) else p["game"]
                rows.append((p["id"], p["gameKey"], fa, p["title"], p["cat"],
                             p["price"], p.get("old"), p.get("badge")))
            conn.executemany(
                "INSERT OR REPLACE INTO products"
                "(id, game_key, game, title, category, price, old_price, badge)"
                " VALUES (?,?,?,?,?,?,?,?)", rows)


def is_valid_player_id(value: str) -> bool:
    return bool(_PLAYER_ID_RE.match(value or ""))


def is_valid_tracking(code: str) -> bool:
    return bool(_TRACKING_RE.match(code or ""))


class OrderError(ValueError):
    """Client-visible order validation error (message is safe to return)."""


# Categories whose packs are charged to a player account: they MUST carry a
# player_id (mirrors the checkout form's ≥4-char rule). Gift-card codes are
# delivered by email, so player_id is optional there — but still charset-checked
# when present.
CATEGORIES_REQUIRING_ID = {"codm", "clash", "other"}


def create_order(items: list[dict], customer_name: str | None = None,
                 customer_contact: str | None = None) -> dict:
    """Validate cart lines against the PRODUCTS table and create a pending order.

    items: [{"product_id": str, "quantity": int, "player_id": str}]
    Prices come exclusively from the DB — any client-sent price is ignored.
    Game packs require a player_id (≥4 chars, safe charset); gift cards may omit
    it. Raises OrderError with a Persian-safe message on any invalid line.
    Returns the order plus a one-order pay_token: /api/order/pay demands it, so
    a bare tracking code (public on the receipt) is not enough to mark paid.
    """
    if not isinstance(items, list) or not (1 <= len(items) <= MAX_ITEMS):
        raise OrderError(f"سبد خرید باید بین ۱ تا {MAX_ITEMS} قلم داشته باشد.")

    seen: set[str] = set()
    clean: list[tuple[str, int, str]] = []
    for it in items:
        if not isinstance(it, dict):
            raise OrderError("هر قلم سبد باید یک آبجکت باشد.")
        pid = str(it.get("product_id", "")).strip()
        qty = it.get("quantity", 1)
        if pid in seen:
            raise OrderError(f"محصول تکراری در سبد: {pid}")
        seen.add(pid)
        if not pid or len(pid) > 40:
            raise OrderError("شناسه محصول نامعتبر است.")
        if not isinstance(qty, int) or isinstance(qty, bool) or not (1 <= qty <= MAX_QTY):
            raise OrderError(f"تعداد برای {pid} باید عددی بین ۱ تا {MAX_QTY} باشد.")
        player_id = str(it.get("player_id", "")).strip()
        if player_id and not is_valid_player_id(player_id):
            raise OrderError("آیدی بازیکن شامل کاراکترهای غیرمجاز است.")
        clean.append((pid, qty, player_id))

    with _connect() as conn:
        priced = []
        total = 0
        item_count = 0
        for pid, qty, player_id in clean:
            row = conn.execute(
                "SELECT id, title, game, category, price FROM products WHERE id = ?",
                (pid,)).fetchone()
            if row is None:
                raise OrderError(f"محصول یافت نشد: {pid}")
            if row["category"] in CATEGORIES_REQUIRING_ID and len(player_id) < 4:
                raise OrderError(
                    f"آیدی بازیکن برای «{row['game']}» الزامی است (حداقل ۴ کاراکتر).")
            total += row["price"] * qty
            item_count += qty
            priced.append((row, qty, player_id))

        for _ in range(5):  # retry on the (astronomically unlikely) tracking collision
            tracking = "CPS-" + "".join(
                secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
            if not conn.execute("SELECT 1 FROM orders WHERE tracking = ?", (tracking,)).fetchone():
                break
        else:
            raise OrderError("خطای تولید کد رهگیری؛ دوباره تلاش کنید.")
        pay_token = secrets.token_urlsafe(24)

        # Link (or create) the customer so receipts carry a name/contact.
        customer_id = None
        cname = (customer_name or "").strip()[:120]
        ccontact = (customer_contact or "").strip()[:120]
        if cname or ccontact:
            cname = cname or "مشتری"
            if ccontact:
                existing = conn.execute(
                    "SELECT id FROM customers WHERE phone = ?", (ccontact,)).fetchone()
                if existing:
                    customer_id = existing["id"]
                    conn.execute("UPDATE customers SET name = ? WHERE id = ?",
                                 (cname, customer_id))
                else:
                    customer_id = conn.execute(
                        "INSERT INTO customers(name, phone) VALUES (?,?)",
                        (cname, ccontact)).lastrowid
            else:
                customer_id = conn.execute(
                    "INSERT INTO customers(name) VALUES (?)", (cname,)).lastrowid

        cur = conn.execute(
            "INSERT INTO orders(tracking, status, total, item_count, pay_token, customer_id)"
            " VALUES (?,?,?,?,?,?)",
            (tracking, "pending", total, item_count, pay_token, customer_id))
        order_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_items(order_id, product_id, title, game, quantity,"
            " unit_price, player_id) VALUES (?,?,?,?,?,?,?)",
            [(order_id, r["id"], r["title"], r["game"], qty, r["price"], player_id)
             for r, qty, player_id in priced])

    return {"tracking": tracking, "total": total, "item_count": item_count,
            "status": "pending", "currency": "toman", "pay_token": pay_token}


def pay_order(tracking: str, token: str) -> dict:
    """pending → paid. Demo stand-in for the real payment-gateway callback.

    The transition requires the per-order pay_token issued by create_order:
    a bare tracking code — which the store displays publicly on the receipt —
    must not suffice to flip money state. Idempotent for already-paid orders
    (no state change possible, and status is publicly readable via GET).
    """
    if not is_valid_tracking(tracking):
        raise OrderError("کد رهگیری نامعتبر است.")
    with _connect() as conn:
        row = conn.execute("SELECT id, status, total, pay_token FROM orders WHERE tracking = ?",
                           (tracking,)).fetchone()
        if row is None:
            raise OrderError("سفارشی با این کد رهگیری یافت نشد.")
        if row["status"] == "paid":
            return {"tracking": tracking, "status": "paid", "total": row["total"]}
        if row["status"] != "pending":
            raise OrderError("این سفارش قابل پرداخت نیست.")
        expected = row["pay_token"] or ""
        if (not token or not expected or
                not secrets.compare_digest(str(token).encode(), expected.encode())):
            raise OrderError("توکن پرداخت نامعتبر است.")
        conn.execute("UPDATE orders SET status='paid', paid_at=datetime('now')"
                     " WHERE id = ?", (row["id"],))
    return {"tracking": tracking, "status": "paid", "total": row["total"]}


def get_order(tracking: str) -> dict | None:
    if not is_valid_tracking(tracking):
        raise OrderError("کد رهگیری نامعتبر است.")
    with _connect() as conn:
        row = conn.execute(
            "SELECT o.id, o.tracking, o.status, o.total, o.item_count, o.created_at, o.paid_at,"
            " c.name AS customer_name, c.phone AS customer_contact"
            " FROM orders o LEFT JOIN customers c ON c.id = o.customer_id"
            " WHERE o.tracking = ?", (tracking,)).fetchone()
        if row is None:
            return None
        items = [dict(r) for r in conn.execute(
            "SELECT product_id, title, game, quantity, unit_price, player_id"
            " FROM order_items WHERE order_id = ?", (row["id"],))]
    out = {k: row[k] for k in ("tracking", "status", "total", "item_count",
                               "created_at", "paid_at", "customer_name",
                               "customer_contact")}
    out["items"] = items
    out["currency"] = "toman"
    return out


def export_orders_json(path: str | Path) -> None:
    """Backup safety: export orders (with items) to JSON."""

    out_path = Path(path)

    with _connect() as conn:
        order_rows = conn.execute(
            """
            SELECT o.id, o.tracking, o.status, o.total, o.created_at, o.paid_at,
                   c.name  AS customer_name,
                   c.phone AS customer_contact
            FROM orders o
            LEFT JOIN customers c ON c.id = o.customer_id
            ORDER BY o.id DESC
            """,
        ).fetchall()

        orders: list[dict[str, Any]] = []
        for o in order_rows:
            items = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT product_id, title, quantity, unit_price, player_id
                    FROM order_items
                    WHERE order_id = ?
                    """,
                    (o["id"],),
                ).fetchall()
            ]
            orders.append(
                {
                    "tracking": o["tracking"],
                    "status": o["status"],
                    "total": o["total"],
                    "currency": "toman",
                    "created_at": o["created_at"],
                    "paid_at": o["paid_at"],
                    "customer_name": o["customer_name"],
                    "customer_contact": o["customer_contact"],
                    "items": items,
                }
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"orders": orders}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def db_stats() -> dict:
    with _connect() as conn:
        products = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
        orders = conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
        paid = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='paid'").fetchone()["c"]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(total),0) s FROM orders WHERE status='paid'").fetchone()["s"]
    return {"products": products, "orders": orders, "paid_orders": paid,
            "paid_total_toman": revenue}


if __name__ == "__main__":
    init_db()
    print("db:", db_stats())

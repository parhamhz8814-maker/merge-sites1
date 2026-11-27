#!/usr/bin/env python3
"""
store_db — SQLite persistence for CP.Shop (ircodmshop.com).

Design
  1. PRODUCTS  seeded from catalog.json. Prices are SERVER-TRUTH: a client can
               never influence what an order costs.
  2. ORDERS    strict lifecycle pending → paid | canceled. Every order snapshots
               the customer's name/contact and each line's player_id, so history
               stays correct even if the catalog or customer record changes.
  3. PRIVACY   order reads mask contact details unless the caller proves
               ownership with the per-order pay_token. Backups never enter the
               repo, and a redacted export exists for anything shared.

Connection policy: one short-lived connection per operation, WAL mode so
readers never block the writer, and a busy timeout so concurrent writers retry
instead of raising "database is locked".
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "cpshop.db"
CATALOG_PATH = HERE / "catalog.json"

MAX_ITEMS = 30
MAX_QTY = 99
MAX_NAME = 120
MAX_CONTACT = 120
MAX_PLAYER_ID = 40

# Pay tokens are single-use and short-lived. Only the SHA-256 hash is stored.
PAY_TOKEN_TTL_MINUTES = 30

# Player ids: letters (any script), digits and the separators games actually use.
_PLAYER_ID_RE = re.compile(r"^[\w\- .@#]{1,40}$", re.UNICODE)
_TRACKING_RE = re.compile(r"^CPS-[A-Z0-9]{8}$")
# Strip control characters from free-text fields before storing them.
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Categories whose packs are charged to a player account and therefore REQUIRE
# a player id. Gift cards / premium accounts are delivered by code or invite,
# so they may omit it (but are still charset-checked when present).
CATEGORIES_REQUIRING_ID = {"codm", "clash", "other"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


_SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS products(
    id          TEXT PRIMARY KEY,
    game_key    TEXT NOT NULL,
    game        TEXT NOT NULL,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       INTEGER NOT NULL CHECK(price > 0),
    old_price   INTEGER CHECK(old_price IS NULL OR old_price >= 0),
    badge       TEXT,
    currency    TEXT NOT NULL DEFAULT 'toman',
    stock       INTEGER NOT NULL DEFAULT 999999 CHECK(stock >= 0),
    is_active   INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_products_game_key ON products(game_key);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_title    ON products(title);
CREATE INDEX IF NOT EXISTS idx_products_active   ON products(is_active);

CREATE TABLE IF NOT EXISTS customers(
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    phone            TEXT,
    email            TEXT,
    game_player_id   TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(email),
    UNIQUE(phone)
);

CREATE TABLE IF NOT EXISTS orders(
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking          TEXT UNIQUE NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK(status IN ('pending','paid','canceled')),
    customer_id       INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    customer_name     TEXT NOT NULL,
    customer_contact  TEXT NOT NULL,
    total             INTEGER NOT NULL CHECK(total > 0),
    item_count        INTEGER NOT NULL CHECK(item_count > 0),
    currency          TEXT NOT NULL DEFAULT 'toman',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at           TEXT,
    pay_token_hash       TEXT,
    pay_token_expires_at TEXT,
    pay_token_used_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_tracking    ON orders(tracking);
CREATE INDEX IF NOT EXISTS idx_orders_status      ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_created_at  ON orders(created_at);

CREATE TABLE IF NOT EXISTS order_items(
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id   TEXT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    title        TEXT NOT NULL,
    game         TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99),
    unit_price   INTEGER NOT NULL CHECK(unit_price > 0),
    player_id    TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product  ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_order_items_player   ON order_items(player_id);
"""


class OrderError(ValueError):
    """Client-visible order validation error (message is safe to return)."""


# --------------------------------------------------------------------- helpers
def _clean_text(value: Any, limit: int) -> str:
    """Trim, drop control characters, and hard-cap length."""
    s = _CTRL_RE.sub("", str(value or "")).strip()
    return s[:limit]


def is_valid_player_id(value: str) -> bool:
    return bool(_PLAYER_ID_RE.match(value or ""))


def is_valid_tracking(code: str) -> bool:
    return bool(_TRACKING_RE.match(code or ""))


def hash_token(raw: str) -> str:
    """SHA-256 hex digest of a pay token. Only hashes are persisted."""
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()


def new_pay_token() -> tuple[str, str]:
    """Return (raw_token, token_hash). The raw value is shown to the client once."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def mask_contact(contact: str | None) -> str:
    """Partially hide a phone/telegram handle for unauthenticated reads."""
    s = str(contact or "")
    if not s:
        return ""
    if len(s) <= 4:
        return "*" * len(s)
    if "@" in s:                       # telegram handle / email
        local, _, domain = s.partition("@")
        return (local[:2] + "***@" + domain) if domain else s[:2] + "***"
    return s[:3] + "*" * max(1, len(s) - 5) + s[-2:]


# ---------------------------------------------------------------- schema + seed
def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by older versions."""
    def cols(table: str) -> set[str]:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

    p = cols("products")
    for name, ddl in (
        ("currency", "TEXT NOT NULL DEFAULT 'toman'"),
        ("stock", "INTEGER NOT NULL DEFAULT 999999"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
        ("created_at", "TEXT"),
    ):
        if name not in p:
            conn.execute(f"ALTER TABLE products ADD COLUMN {name} {ddl}")
    conn.execute("UPDATE products SET created_at = datetime('now') WHERE created_at IS NULL")

    o = cols("orders")
    for name, ddl in (
        ("customer_id", "INTEGER"),
        ("customer_name", "TEXT"),
        ("customer_contact", "TEXT"),
        ("currency", "TEXT NOT NULL DEFAULT 'toman'"),
        ("pay_token", "TEXT"),
        ("pay_token_hash", "TEXT"),
        ("pay_token_expires_at", "TEXT"),
        ("pay_token_used_at", "TEXT"),
    ):
        if name not in o:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {ddl}")

    # Migrate any legacy raw pay_token to a hash. Raw tokens must never sit in
    # the database: a leaked DB file would otherwise hand out payment authority.
    if "pay_token" in o:
        legacy = conn.execute(
            "SELECT id, pay_token FROM orders WHERE pay_token IS NOT NULL AND pay_token != ''"
        ).fetchall()
        for r in legacy:
            conn.execute(
                "UPDATE orders SET pay_token_hash = ? WHERE id = ?",
                (hash_token(r["pay_token"]), r["id"]),
            )
        if legacy:
            conn.execute("UPDATE orders SET pay_token = NULL")

    # Backfill the denormalised customer snapshot so historical orders keep
    # their receipt details.
    conn.execute(
        """
        UPDATE orders
           SET customer_name    = COALESCE(customer_name,
                    (SELECT name  FROM customers c WHERE c.id = orders.customer_id), 'مشتری'),
               customer_contact = COALESCE(customer_contact,
                    (SELECT phone FROM customers c WHERE c.id = orders.customer_id), 'نامشخص')
         WHERE customer_name IS NULL OR customer_contact IS NULL
        """
    )

    oi = cols("order_items")
    if "player_id" not in oi:
        conn.execute("ALTER TABLE order_items ADD COLUMN player_id TEXT NOT NULL DEFAULT ''")


def _seed_products(conn: sqlite3.Connection) -> int:
    """Upsert every catalog product. Idempotent: re-running never duplicates.

    Uses ON CONFLICT DO UPDATE rather than INSERT OR REPLACE: REPLACE deletes
    the existing row first, which trips the order_items → products RESTRICT
    foreign key and would break historical orders.
    """
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    games = raw.get("games") or {}
    products = raw.get("products") or []

    rows: list[tuple[Any, ...]] = []
    for p in products:
        pid = _clean_text(p.get("id"), 60)
        if not pid:
            continue
        game_key = _clean_text(p.get("gameKey"), 60)
        game_meta = games.get(game_key) if isinstance(games, dict) else None
        game = _clean_text(
            (game_meta or {}).get("fa") if isinstance(game_meta, dict) else None, 80
        ) or _clean_text(p.get("game"), 80)
        rows.append((
            pid,
            game_key,
            game,
            _clean_text(p.get("title"), 200),
            _clean_text(p.get("cat"), 40),
            int(p.get("price") or 0),
            (int(p["old"]) if p.get("old") is not None else None),
            _clean_text(p.get("badge"), 40) or None,
        ))

    conn.executemany(
        """
        INSERT INTO products(id, game_key, game, title, category, price, old_price, badge)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            game_key  = excluded.game_key,
            game      = excluded.game,
            title     = excluded.title,
            category  = excluded.category,
            price     = excluded.price,
            old_price = excluded.old_price,
            badge     = excluded.badge
        """,
        rows,
    )
    return len(rows)


def init_db(seed: bool = True) -> None:
    """Create the schema, run migrations, and optionally seed the catalog."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        if seed:
            _seed_products(conn)


# ------------------------------------------------------------------- ordering
def create_order(
    items: list[dict],
    customer_name: str | None = None,
    customer_contact: str | None = None,
    claimed_total: int | None = None,
) -> dict:
    """Create a pending order priced exclusively from the products table.

    items: [{"product_id": str, "quantity": int, "player_id": str}, ...]

    Customer name and contact are REQUIRED — a top-up order is undeliverable
    without a way to reach the buyer. They are snapshotted onto the order.

    claimed_total: if the client states a total, it MUST equal the server
    computed sum of the lines; otherwise the order is rejected. This catches
    a client that has drifted from the catalog (stale price, wrong quantity)
    instead of silently charging a different amount than shown.
    """
    if not isinstance(items, list) or not (1 <= len(items) <= MAX_ITEMS):
        raise OrderError(f"سبد خرید باید بین ۱ تا {MAX_ITEMS} قلم داشته باشد.")

    cname = _clean_text(customer_name, MAX_NAME)
    ccontact = _clean_text(customer_contact, MAX_CONTACT)
    if len(cname) < 2:
        raise OrderError("نام مشتری را وارد کنید (حداقل ۲ کاراکتر).")
    if len(ccontact) < 5:
        raise OrderError("شماره تماس یا آیدی تلگرام را وارد کنید (حداقل ۵ کاراکتر).")

    # ---- validate every line before touching the database
    seen: set[str] = set()
    clean: list[tuple[str, int, str]] = []
    for it in items:
        if not isinstance(it, dict):
            raise OrderError("هر قلم سبد باید یک آبجکت باشد.")

        pid = _clean_text(it.get("product_id"), 60)
        qty = it.get("quantity", 1)
        player_id = _clean_text(it.get("player_id"), MAX_PLAYER_ID)

        if not pid:
            raise OrderError("شناسه محصول نامعتبر است.")
        if pid in seen:
            raise OrderError(f"محصول تکراری در سبد: {pid}")
        seen.add(pid)

        if not isinstance(qty, int) or isinstance(qty, bool) or not (1 <= qty <= MAX_QTY):
            raise OrderError(f"تعداد برای {pid} باید عددی بین ۱ تا {MAX_QTY} باشد.")

        if player_id and not is_valid_player_id(player_id):
            raise OrderError("آیدی بازیکن شامل کاراکترهای غیرمجاز است.")

        clean.append((pid, qty, player_id))

    with _connect() as conn:
        priced: list[tuple[sqlite3.Row, int, str]] = []
        total = 0
        item_count = 0

        for pid, qty, player_id in clean:
            row = conn.execute(
                "SELECT id, title, game, category, price, stock, is_active"
                "  FROM products WHERE id = ?",
                (pid,),
            ).fetchone()
            if row is None:
                raise OrderError(f"محصول یافت نشد: {pid}")
            if not int(row["is_active"]):
                raise OrderError(f"این محصول در حال حاضر موجود نیست: {row['title']}")
            if int(row["stock"]) < qty:
                raise OrderError(f"موجودی «{row['title']}» کافی نیست.")
            if row["category"] in CATEGORIES_REQUIRING_ID and len(player_id) < 4:
                raise OrderError(
                    f"آیدی بازیکن برای «{row['game']}» الزامی است (حداقل ۴ کاراکتر)."
                )
            total += int(row["price"]) * qty
            item_count += qty
            priced.append((row, qty, player_id))

        if total <= 0:
            raise OrderError("مبلغ سفارش معتبر نیست.")

        # ---- integrity: recomputed total must match what the client displayed
        if claimed_total is not None:
            try:
                claimed = int(claimed_total)
            except (TypeError, ValueError):
                raise OrderError("مبلغ ارسالی معتبر نیست.")
            if claimed != total:
                raise OrderError(
                    "مبلغ سبد با قیمت‌های فعلی فروشگاه هم‌خوان نیست. "
                    "صفحه را تازه کنید و دوباره تلاش کنید."
                )

        # ---- unique tracking code
        tracking = ""
        for _ in range(8):
            candidate = "CPS-" + "".join(
                secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8)
            )
            if not conn.execute(
                "SELECT 1 FROM orders WHERE tracking = ?", (candidate,)
            ).fetchone():
                tracking = candidate
                break
        if not tracking:
            raise OrderError("خطای تولید کد رهگیری؛ دوباره تلاش کنید.")

        pay_token, pay_token_hash = new_pay_token()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=PAY_TOKEN_TTL_MINUTES)
        ).strftime("%Y-%m-%d %H:%M:%S")

        # ---- customer record (deduped by phone) + snapshot on the order
        customer_id = None
        existing = conn.execute(
            "SELECT id FROM customers WHERE phone = ?", (ccontact,)
        ).fetchone()
        if existing:
            customer_id = existing["id"]
            conn.execute("UPDATE customers SET name = ? WHERE id = ?", (cname, customer_id))
        else:
            customer_id = conn.execute(
                "INSERT INTO customers(name, phone) VALUES (?,?)", (cname, ccontact)
            ).lastrowid

        cur = conn.execute(
            """
            INSERT INTO orders(
                tracking, status, customer_id, customer_name, customer_contact,
                total, item_count, currency,
                pay_token_hash, pay_token_expires_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (tracking, "pending", customer_id, cname, ccontact,
             total, item_count, "toman", pay_token_hash, expires_at),
        )
        order_id = cur.lastrowid

        conn.executemany(
            """
            INSERT INTO order_items(
                order_id, product_id, title, game, quantity, unit_price, player_id
            ) VALUES (?,?,?,?,?,?,?)
            """,
            [
                (order_id, r["id"], r["title"], r["game"], qty, int(r["price"]), player_id)
                for r, qty, player_id in priced
            ],
        )

    return {
        "tracking": tracking,
        "total": total,
        "item_count": item_count,
        "status": "pending",
        "currency": "toman",
        "pay_token": pay_token,
    }


def _token_state(conn: sqlite3.Connection, order_id: int) -> dict:
    """Current token state for an order: hash, expiry, used-at."""
    return dict(conn.execute(
        "SELECT pay_token_hash, pay_token_expires_at, pay_token_used_at"
        "  FROM orders WHERE id = ?", (order_id,)
    ).fetchone())


def _check_token(row: dict, token: str) -> None:
    """Validate a pay token: hash match, not expired, not already used."""
    expected = str(row.get("pay_token_hash") or "")
    if not expected or not token:
        raise OrderError("توکن پرداخت نامعتبر است.")
    if not secrets.compare_digest(hash_token(token).encode(), expected.encode()):
        raise OrderError("توکن پرداخت نامعتبر است.")

    used = row.get("pay_token_used_at")
    if used:
        raise OrderError("این توکن قبلاً استفاده شده است.")

    expires = row.get("pay_token_expires_at")
    if expires:
        try:
            exp = datetime.strptime(str(expires), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            exp = None
        if exp is not None and datetime.now(timezone.utc) > exp:
            raise OrderError("مهلت پرداخت این سفارش به پایان رسیده است.")


def pay_order(tracking: str, token: str) -> dict:
    """pending → paid. Requires the per-order pay_token issued at creation.

    The token is single-use (burned on success) and expires after
    PAY_TOKEN_TTL_MINUTES. Only its hash is stored, so a database leak does not
    hand out payment authority.
    """
    if not is_valid_tracking(tracking):
        raise OrderError("کد رهگیری نامعتبر است.")
    if not isinstance(token, str) or not token:
        raise OrderError("توکن پرداخت نامعتبر است.")

    with _connect() as conn:
        row = conn.execute(
            "SELECT id, status, total, pay_token_hash, pay_token_expires_at,"
            "       pay_token_used_at"
            "  FROM orders WHERE tracking = ?",
            (tracking,),
        ).fetchone()
        if row is None:
            raise OrderError("سفارشی با این کد رهگیری یافت نشد.")
        if row["status"] == "paid":
            # Idempotent for a retried gateway callback: the token that actually
            # paid this order is accepted again (it is already burned), but a
            # bare tracking code or any other token is not.
            expected = str(row["pay_token_hash"] or "")
            if not expected or not secrets.compare_digest(
                hash_token(token).encode(), expected.encode()
            ):
                raise OrderError("توکن پرداخت نامعتبر است.")
            return {"tracking": tracking, "status": "paid", "total": row["total"],
                    "currency": "toman"}
        if row["status"] != "pending":
            raise OrderError("این سفارش قابل پرداخت نیست.")

        _check_token(dict(row), token)

        conn.execute("BEGIN IMMEDIATE")
        try:
            items = conn.execute(
                "SELECT product_id, quantity, unit_price FROM order_items WHERE order_id = ?",
                (row["id"],),
            ).fetchall()

            # Re-verify the stored total against the stored lines. Guards
            # against a corrupted or tampered row being paid.
            recomputed = sum(int(it["unit_price"]) * int(it["quantity"]) for it in items)
            if recomputed != int(row["total"]):
                raise OrderError(
                    "مبلغ سفارش با اقلام آن هم‌خوان نیست؛ سفارش قابل پرداخت نیست."
                )

            for it in items:
                prod = conn.execute(
                    "SELECT stock FROM products WHERE id = ?", (it["product_id"],)
                ).fetchone()
                if prod is None or int(prod["stock"]) < int(it["quantity"]):
                    raise OrderError("موجودی یکی از اقلام در زمان پرداخت کافی نیست.")
            conn.executemany(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                [(int(it["quantity"]), it["product_id"]) for it in items],
            )
            # Burn the token in the same transaction as the status change.
            conn.execute(
                "UPDATE orders"
                "   SET status='paid', paid_at=datetime('now'),"
                "       pay_token_used_at=datetime('now')"
                " WHERE id = ?",
                (row["id"],),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return {"tracking": tracking, "status": "paid", "total": row["total"],
            "currency": "toman"}


def cancel_order(tracking: str, token: str) -> dict:
    """pending → canceled. Same token gate as payment."""
    if not is_valid_tracking(tracking):
        raise OrderError("کد رهگیری نامعتبر است.")
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, status, pay_token_hash, pay_token_expires_at, pay_token_used_at"
            "  FROM orders WHERE tracking = ?",
            (tracking,),
        ).fetchone()
        if row is None:
            raise OrderError("سفارشی با این کد رهگیری یافت نشد.")
        if row["status"] == "canceled":
            return {"tracking": tracking, "status": "canceled"}
        if row["status"] != "pending":
            raise OrderError("این سفارش قابل لغو نیست.")
        _check_token(dict(row), token)
        conn.execute(
            "UPDATE orders SET status='canceled', pay_token_used_at=datetime('now')"
            " WHERE id = ?",
            (row["id"],),
        )
    return {"tracking": tracking, "status": "canceled"}


def get_order(tracking: str, token: str | None = None) -> dict | None:
    """Read an order. Contact details are masked unless the pay_token is given.

    The tracking code is printed on receipts and may be shared, so it must not
    be enough on its own to reveal the buyer's phone number.
    """
    if not is_valid_tracking(tracking):
        raise OrderError("کد رهگیری نامعتبر است.")

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, tracking, status, total, item_count, currency,
                   created_at, paid_at, customer_name, customer_contact,
                   pay_token_hash, pay_token_expires_at, pay_token_used_at
              FROM orders WHERE tracking = ?
            """,
            (tracking,),
        ).fetchone()
        if row is None:
            return None

        items = [
            dict(r)
            for r in conn.execute(
                """
                SELECT product_id, title, game, quantity, unit_price, player_id
                  FROM order_items WHERE order_id = ? ORDER BY id
                """,
                (row["id"],),
            ).fetchall()
        ]

    expected = str(row["pay_token_hash"] or "")
    owns = bool(token and expected) and secrets.compare_digest(
        hash_token(token).encode(), expected.encode()
    )
    return {
        "tracking": row["tracking"],
        "status": row["status"],
        "total": row["total"],
        "currency": row["currency"],
        "item_count": row["item_count"],
        "created_at": row["created_at"],
        "paid_at": row["paid_at"],
        "customer_name": row["customer_name"] if owns else None,
        "customer_contact": row["customer_contact"] if owns else mask_contact(row["customer_contact"]),
        "items": items,
    }


# --------------------------------------------------------------------- backups
def export_orders_json(path: str | Path, redact: bool = False) -> int:
    """Dump orders (with items) to JSON. Returns the number of orders written.

    redact=True masks customer contact and player ids — use it for any copy
    that is shared, uploaded, or committed. The unredacted export is a
    production backup and must never enter version control.
    """
    out_path = Path(path)
    with _connect() as conn:
        order_rows = conn.execute(
            """
            SELECT id, tracking, status, total, currency, created_at, paid_at,
                   customer_name, customer_contact
              FROM orders ORDER BY id DESC
            """
        ).fetchall()

        orders: list[dict[str, Any]] = []
        for o in order_rows:
            items = [
                dict(r)
                for r in conn.execute(
                    "SELECT product_id, title, quantity, unit_price, player_id"
                    "  FROM order_items WHERE order_id = ?",
                    (o["id"],),
                ).fetchall()
            ]
            if redact:
                for it in items:
                    it["player_id"] = mask_contact(it["player_id"])
            orders.append({
                "tracking": o["tracking"],
                "status": o["status"],
                "total": o["total"],
                "currency": o["currency"],
                "created_at": o["created_at"],
                "paid_at": o["paid_at"],
                "customer_name": ((o["customer_name"] or "")[:1] + "***") if redact else o["customer_name"],
                "customer_contact": mask_contact(o["customer_contact"]) if redact else o["customer_contact"],
                "items": items,
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"orders": orders}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(orders)


# ----------------------------------------------------------------------- stats
def db_stats() -> dict:
    """Internal stats (revenue included) — CLI/admin use only, never public."""
    with _connect() as conn:
        products = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) c FROM products WHERE is_active=1").fetchone()["c"]
        orders = conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
        paid = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='paid'").fetchone()["c"]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(total),0) s FROM orders WHERE status='paid'"
        ).fetchone()["s"]
    return {"products": products, "active_products": active, "orders": orders,
            "paid_orders": paid, "paid_total_toman": revenue}


def public_stats() -> dict:
    """Safe for an unauthenticated endpoint: catalog size only, no revenue."""
    with _connect() as conn:
        products = conn.execute(
            "SELECT COUNT(*) c FROM products WHERE is_active=1"
        ).fetchone()["c"]
    return {"products": products}


if __name__ == "__main__":
    init_db()
    print("db:", db_stats())

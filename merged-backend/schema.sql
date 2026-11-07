-- CP.Shop backend database schema (SQLite)
-- Versioning file. store_db.py runs the equivalent SQL via _SCHEMA.

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

CREATE INDEX IF NOT EXISTS idx_products_game_key ON products(game_key);
CREATE INDEX IF NOT EXISTS idx_products_category  ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_title     ON products(title);

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

CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_customers_game_player_id ON customers(game_player_id);

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

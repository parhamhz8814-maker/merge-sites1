from __future__ import annotations

import store_db
from shopping_cart import ShoppingCart


def main():
    store_db.init_db(seed=True)

    cart = ShoppingCart()
    cart.add_item("codm-80", quantity=2, player_id="12345678")
    cart.add_item("codm-bp", quantity=1, player_id="12345678")

    total = cart.calculate_total()

    # sanity check against DB directly
    db_total = store_db._connect().execute(
        "SELECT price FROM products WHERE id in (?, ?)",
        ("codm-80", "codm-bp"),
    ).fetchall()
    prices = {r[0]: r[0] for r in []}  # dummy to keep structure
    # re-query with ids to avoid relying on row_factory keys
    r1 = store_db._connect().execute("SELECT price FROM products WHERE id = ?", ("codm-80",)).fetchone()
    r2 = store_db._connect().execute("SELECT price FROM products WHERE id = ?", ("codm-bp",)).fetchone()
    expected = int(r1[0]) * 2 + int(r2[0]) * 1

    assert total == expected, f"total {total} != expected {expected}"

    order_items = cart.to_order_items()
    assert len(order_items) == 2

    # test create_order writes to DB (pending)
    order = store_db.create_order(order_items)
    assert order["status"] == "pending"
    assert order["item_count"] == 3

    # payment completes when correct token provided
    paid = store_db.pay_order(order["tracking"], order["pay_token"])
    assert paid["status"] == "paid"

    got = store_db.get_order(order["tracking"])
    assert got is not None
    assert got["status"] == "paid"

    print("ShoppingCart + create_order + pay_order: OK")


if __name__ == "__main__":
    main()

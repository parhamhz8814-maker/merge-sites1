from __future__ import annotations

import store_db
from shopping_cart import ShoppingCart


def main():
    store_db.init_db(seed=True)

    # pick two real product ids from the seeded catalog
    with store_db._connect() as conn:
        rows = conn.execute(
            "SELECT id FROM products WHERE category='codm' AND is_active=1 LIMIT 2"
        ).fetchall()
    pid, pid2 = rows[0]["id"], rows[1]["id"]

    cart = ShoppingCart()
    cart.add_item(pid, quantity=2, player_id="12345678")
    cart.add_item(pid2, quantity=1, player_id="12345678")

    total = cart.calculate_total()

    # sanity check against DB directly
    r1 = store_db._connect().execute("SELECT price FROM products WHERE id = ?", (pid,)).fetchone()
    r2 = store_db._connect().execute("SELECT price FROM products WHERE id = ?", (pid2,)).fetchone()
    expected = int(r1[0]) * 2 + int(r2[0]) * 1

    assert total == expected, f"total {total} != expected {expected}"

    order_items = cart.to_order_items()
    assert len(order_items) == 2

    # test create_order writes to DB (pending)
    order = store_db.create_order(
        order_items,
        customer_name="Test User",
        customer_contact="09120000000",
    )
    assert order["status"] == "pending"
    assert order["item_count"] == 3

    # payment completes when correct token provided
    paid = store_db.pay_order(order["tracking"], order["pay_token"])
    assert paid["status"] == "paid"

    got = store_db.get_order(order["tracking"], order["pay_token"])
    assert got is not None
    assert got["status"] == "paid"

    print("ShoppingCart + create_order + pay_order: OK")


if __name__ == "__main__":
    main()

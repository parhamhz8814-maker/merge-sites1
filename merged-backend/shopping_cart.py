from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import store_db


@dataclass
class CartLine:
    product_id: str
    quantity: int
    player_id: str = ""


class ShoppingCart:
    """In-memory cart used by the purchase flow.

    Notes:
      - Pricing is server-side from store_db.products.
      - For game packs that require an account id, player_id must be
        provided (store_db.create_order enforces the >=4 chars rule).
    """

    def __init__(self):
        # keyed by product_id to avoid duplicate lines
        self._lines: Dict[str, CartLine] = {}

    def add_item(self, product_id: str, quantity: int = 1, player_id: str = "") -> None:
        if not product_id:
            raise ValueError("product_id is required")
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise ValueError("quantity must be int")
        if quantity < 1 or quantity > store_db.MAX_QTY:
            raise ValueError(f"quantity must be between 1 and {store_db.MAX_QTY}")

        key = str(product_id).strip()
        player_id = str(player_id).strip() if player_id is not None else ""

        if key in self._lines:
            # merge quantities; keep player_id from existing line unless caller provides one
            existing = self._lines[key]
            merged_qty = existing.quantity + quantity
            if merged_qty > store_db.MAX_QTY:
                raise ValueError(f"Merged quantity exceeds {store_db.MAX_QTY}")
            existing.quantity = merged_qty
            if player_id:
                existing.player_id = player_id
        else:
            self._lines[key] = CartLine(product_id=key, quantity=quantity, player_id=player_id)

    def remove_item(self, product_id: str) -> None:
        if product_id is None:
            return
        self._lines.pop(str(product_id).strip(), None)

    def clear(self) -> None:
        self._lines.clear()

    @property
    def items(self) -> List[CartLine]:
        return list(self._lines.values())

    def calculate_total(self) -> int:
        """Calculate total from the server-side products table."""
        # ensure schema + seeded products exist
        store_db.init_db(seed=True)

        total = 0
        for line in self._lines.values():
            # fetch product price
            row = store_db._connect().execute("SELECT id, price FROM products WHERE id = ?", (line.product_id,)).fetchone()
            if row is None:
                raise ValueError(f"Unknown product_id: {line.product_id}")
            total += int(row["price"]) * int(line.quantity)
        return total

    def to_order_items(self) -> List[dict]:
        """Convert cart lines into the shape store_db.create_order expects."""
        out: List[dict] = []
        for line in self._lines.values():
            out.append({
                "product_id": line.product_id,
                "quantity": int(line.quantity),
                "player_id": line.player_id,
            })
        return out

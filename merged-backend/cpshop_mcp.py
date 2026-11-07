#!/usr/bin/env python3
"""
cpshop_mcp — MCP server for the CP.Shop (سی‌پی شاپ) game-currency store.

Exposes the store catalog to LLM agents over stdio:

  - cpshop_list_games          List all games with product counts
  - cpshop_search_products     Search the 37-product catalog (Persian or Latin)
  - cpshop_get_product         Full product details incl. required account ID field
  - cpshop_estimate_cart       Price a cart (line totals, savings, per-item errors)
  - cpshop_store_stats         Catalog-wide statistics

Data source: catalog.json (extracted from the store's PRODUCTS array in
index.html). Update catalog.json when the store catalog changes.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from functools import lru_cache
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

try:
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # v1 exposes ValueError-based tool failures
    ToolError = ValueError

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # MCP 2.x renamed FastMCP to MCPServer
    FastMCP = None

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"


class StoreData:
    """Immutable in-memory snapshot of the store catalog."""

    def __init__(self, raw: dict):
        self.meta = raw["meta"]
        self.currency = raw["meta"]["currency"]
        self.products: dict[str, dict] = {p["id"]: p for p in raw["products"]}
        # categories/games may be JSON objects keyed by id or arrays of {key,...}
        def _keyed(obj):
            if isinstance(obj, dict):
                return [{**v, "key": k} for k, v in obj.items()]
            return list(obj)

        cats = _keyed(raw["categories"])
        games = _keyed(raw["games"])
        self.categories: dict[str, dict] = {c["key"]: c for c in cats}
        self.games: dict[str, dict] = {g["key"]: g for g in games}
        # search aliases: latin + ascii-folded persian + game key + category
        self._search_index: list[tuple[str, dict]] = []
        for p in raw["products"]:
            game = self.games.get(p["gameKey"], {})
            cat = self.categories.get(p["cat"], {})
            haystack = " ".join(
                filter(None, [
                    p["id"], p["game"], p["title"], p["desc"],
                    game.get("latin", ""), game.get("aliases", "") and " ".join(game["aliases"]),
                    p["gameKey"], p["cat"], cat.get("latin", ""),
                ])
            ).lower()
            self._search_index.append((haystack, p))

    @property
    def product_list(self) -> list[dict]:
        return list(self.products.values())


@lru_cache(maxsize=1)
def _load_store() -> StoreData:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return StoreData(json.load(f))


def _ascii_fold(text: str) -> str:
    """Map Persian/Arabic characters to latin approximations for search."""
    table = str.maketrans({
        "آ": "a", "ا": "a", "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j",
        "چ": "ch", "ح": "h", "خ": "kh", "د": "d", "ذ": "z", "ر": "r", "ز": "z",
        "ژ": "zh", "س": "s", "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z",
        "ع": "a", "غ": "gh", "ف": "f", "ق": "gh", "ک": "k", "گ": "g", "ل": "l",
        "م": "m", "ن": "n", "و": "v", "ه": "h", "ی": "y",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        "٪": "%", "‌": " ",  # ZWNJ -> space
    })
    return text.translate(table)


def _matches(query: str, haystack: str) -> bool:
    """Match query against haystack, trying ascii-folded persian too."""
    q = query.lower().strip()
    if q in haystack:
        return True
    fq = _ascii_fold(q)
    if fq and fq in _ascii_fold(haystack):
        return True
    # token match (all tokens must appear)
    toks = [t for t in fq.split() if len(t) > 1]
    if toks:
        fh = _ascii_fold(haystack)
        return all(t in fh for t in toks)
    return False


def _toman(amount: int) -> str:
    return f"{amount:,} toman"


def _product_brief(p: dict, store: StoreData) -> dict:
    game = store.games.get(p["gameKey"], {})
    return {
        "id": p["id"],
        "game": p["game"],
        "game_latin": game.get("latin", p["gameKey"]),
        "title": p["title"],
        "price": p["price"],
        "old_price": p["old"],
        "discount_percent": round((1 - p["price"] / p["old"]) * 100) if p["old"] else 0,
        "badge": p.get("badge"),
        "category": p["cat"],
    }


# ---------------------------------------------------------------------------
# Server + input models
# ---------------------------------------------------------------------------

if FastMCP is not None:
    try:
        # stateless: no session ids; json_response: plain JSON, not SSE streams —
        # simplest possible transport for the site's chat-widget MCP client.
        mcp = FastMCP("cpshop_mcp", stateless_http=True, json_response=True)
    except TypeError:  # older SDK without these options
        mcp = FastMCP("cpshop_mcp")
else:
    # MCP 2.x renamed FastMCP -> MCPServer; support both versions without
    # forcing pinning to an older SDK.
    from mcp.server.mcpserver import MCPServer
    mcp = MCPServer("cpshop_mcp")


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


QueryStr = Annotated[str, Field(
    min_length=2, max_length=100,
    description="Search text: game name (Persian or Latin), currency, or product id. "
                "Examples: 'codm', 'فورتنایت', 'جم', 'clash', 'gift'")]
ProductIdStr = Annotated[str, Field(
    min_length=2, max_length=40,
    description="Product identifier from search results, e.g. 'codm-80', 'cr-gem2', 'gift-steam'")]


class CartItemInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    product_id: str = Field(..., description="Product identifier, e.g. 'codm-80'", min_length=2, max_length=40)
    quantity: int = Field(default=1, ge=1, le=99, description="How many units (1-99)")


CartItems = Annotated[list[CartItemInput], Field(
    min_length=1, max_length=30, description="Cart lines (1-30 items)")]


def _reject_duplicate_ids(items: list[CartItemInput]) -> None:
    ids = [i.product_id for i in items]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ToolError(f"Duplicate product_id lines: {sorted(dupes)} — merge them into one line with a higher quantity")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="cpshop_list_games",
    annotations={
        "title": "List CP.Shop Games",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False,
    },
)
async def cpshop_list_games(response_format: ResponseFormat = ResponseFormat.MARKDOWN) -> str:
    """List every game available in the CP.Shop store with its product count and category.

    Use this first when exploring the catalog: it shows all 16 games (Call of Duty Mobile,
    Clash Royale, Fortnite, Valorant, gift cards, ...) with how many top-up packages each
    has. Then use cpshop_search_products to find specific packages.

    Args:
        response_format: 'markdown' for human-readable list, 'json' for machine-readable.

    Returns:
        str: Game list. JSON schema:
        {"store": str, "currency": str, "total_games": int, "total_products": int,
         "games": [{"key": str, "name_fa": str, "latin": str, "category": str,
                    "category_fa": str, "product_count": int, "example_titles": [str]}]}

    Examples:
        - Use when: "چه بازی‌هایی دارید؟" / "What games can I top up?"
        - Don't use when: you need prices (use cpshop_search_products)
    """
    store = _load_store()
    counts: dict[str, int] = {}
    for p in store.product_list:
        counts[p["gameKey"]] = counts.get(p["gameKey"], 0) + 1

    games = []
    for key, g in store.games.items():
        prods = [p for p in store.product_list if p["gameKey"] == key]
        cat = store.categories[prods[0]["cat"]] if prods else {}
        games.append({
            "key": key,
            "name_fa": g["fa"],
            "latin": g["latin"],
            "category": prods[0]["cat"] if prods else None,
            "category_fa": cat.get("fa", ""),
            "product_count": counts.get(key, 0),
            "example_titles": [p["title"] for p in prods[:3]],
        })
    games.sort(key=lambda g: -g["product_count"])

    payload = {
        "store": store.meta["name"],
        "currency": store.currency,
        "total_games": len(games),
        "total_products": len(store.products),
        "games": games,
    }
    if response_format == ResponseFormat.JSON:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [f"# {store.meta['name']} — {len(games)} بازی، {len(store.products)} محصول", ""]
    for g in games:
        lines.append(f"- **{g['name_fa']}** ({g['latin']}) — {g['product_count']} بسته — دسته: {g['category_fa']}")
    return "\n".join(lines)


@mcp.tool(
    name="cpshop_search_products",
    annotations={
        "title": "Search CP.Shop Products",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False,
    },
)
async def cpshop_search_products(
    query: QueryStr,
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum results to return")] = 20,
    offset: Annotated[int, Field(ge=0, description="Number of results to skip for pagination")] = 0,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """Search the CP.Shop catalog for top-up packages by game, currency, or product id.

    Matches Persian and Latin names (e.g. 'فورتنایت', 'fortnite', 'vbucks', 'جم', 'gem',
    'codm', 'گیفت کارت'). Also understands Persian characters typed phonetically. Returns
    prices in toman with discount info, paginated.

    Args:
        query (str): Search text, min 2 chars (e.g. 'fortnite', 'جم', 'codm-880')
        limit (int): Max results 1-50 (default 20)
        offset (int): Skip count for pagination (default 0)
        response_format: 'markdown' or 'json'

    Returns:
        str: Results with pagination metadata. JSON schema:
        {"query": str, "total": int, "count": int, "offset": int, "has_more": bool,
         "next_offset": int | null,
         "products": [{"id": str, "game": str, "game_latin": str, "title": str,
                       "price": int, "old_price": int | null, "discount_percent": int,
                       "badge": str | null, "category": str}]}

    Examples:
        - Use when: "پکیج‌های فورتنایت چنده؟" -> query='fortnite'
        - Use when: "cheapest CP pack" -> query='codm'
        - Don't use when: you already have a product id (use cpshop_get_product)
    """
    if not query.strip():
        raise ValueError("Query cannot be empty or whitespace only")
    store = _load_store()
    hits = [p for hay, p in store._search_index if _matches(query, hay)]
    total = len(hits)
    window = hits[offset: offset + limit]
    has_more = total > offset + len(window)

    if not window:
        if total == 0:
            games_fa = "، ".join(g["fa"] for g in list(store.games.values())[:8])
            return (f"No products found matching '{query}'. Try a game name like: "
                    f"{games_fa} ... or a currency like جم / سی پی / یوسی, or list all games "
                    f"with cpshop_list_games.")
        return json.dumps({"query": query, "total": total, "count": 0,
                           "offset": offset, "has_more": False, "products": []},
                          ensure_ascii=False, indent=2)

    products = [_product_brief(p, store) for p in window]
    payload = {
        "query": query, "total": total, "count": len(window),
        "offset": offset, "has_more": has_more,
        "next_offset": offset + len(window) if has_more else None,
        "products": products,
    }
    if response_format == ResponseFormat.JSON:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [f"# نتایج جستجو برای «{query}» — {total} مورد", ""]
    for p in window:
        disc = f" (تخفیف {products[window.index(p)]['discount_percent']}٪ از {_toman(p['old'])})" if p["old"] else ""
        badge = f" [{p['badge']}]" if p.get("badge") else ""
        lines.append(f"- **{p['title']}** — {p['game']}{badge} — {_toman(p['price'])}{disc} — id: `{p['id']}`")
    if has_more:
        lines.append(f"\nنمایش {len(window)} از {total} — برای ادامه offset={offset + len(window)}")
    return "\n".join(lines)


@mcp.tool(
    name="cpshop_get_product",
    annotations={
        "title": "Get CP.Shop Product Details",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False,
    },
)
async def cpshop_get_product(product_id: ProductIdStr) -> str:
    """Get full details for one CP.Shop product by its id.

    Returns price, old price, discount, description, the game it belongs to, and —
    importantly — the account identifier the buyer must provide (Player ID, Player Tag,
    UID, or email for gift-card codes) with an example of valid format.

    Args:
        product_id (str): Exact id from search results (e.g. 'codm-80', 'gift-steam')

    Returns:
        str: JSON with full product schema:
        {"id": str, "game": str, "game_latin": str, "title": str, "description": str,
         "price": int, "old_price": int | null, "discount_percent": int,
         "badge": str | null, "category": str, "category_fa": str,
         "required_account_field": {"label_fa": str, "example": str},
         "delivery": str}

    Examples:
        - Use when: "جزئیات بسته codm-880 رو بگو" -> product_id='codm-880'
        - Use when: buyer asks "what info do you need from me?" for a specific pack
        - Don't use when: exploring what exists (use cpshop_search_products first)
    """
    store = _load_store()
    p = store.products.get(product_id)
    if p is None:
        suggestions = [pid for pid in store.products if product_id.lower()[:3] in pid][:5]
        msg = f"Error: Product '{product_id}' not found."
        if suggestions:
            msg += f" Did you mean one of: {', '.join(suggestions)}?"
        msg += " Use cpshop_search_products to find valid product ids."
        return msg

    game = store.games.get(p["gameKey"], {})
    cat = store.categories[p["cat"]]
    payload = {
        **_product_brief(p, store),
        "description": p["desc"],
        "category_fa": cat["fa"],
        "required_account_field": cat["idField"],
        "delivery": store.meta["delivery"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool(
    name="cpshop_estimate_cart",
    annotations={
        "title": "Estimate CP.Shop Cart Total",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False,
    },
)
async def cpshop_estimate_cart(items: CartItems) -> str:
    """Price a CP.Shop cart: per-line totals, total cost, total savings, and per-item validation.

    Every line is validated against the live catalog; invalid ids or over-limit
    quantities (max 99 per line) are reported per-item without failing the whole cart.
    This is an estimate only — it does not create an order or charge anything.

    Args:
        items (list): 1-30 lines of {product_id: str, quantity: int 1-99};
            duplicate product_ids in separate lines are rejected — merge them.

    Returns:
        str: JSON with cart schema:
        {"currency": str, "line_count": int, "item_count": int,
         "lines": [{"product_id": str, "title": str, "game": str, "quantity": int,
                    "unit_price": int, "line_total": int, "line_savings": int,
                    "status": "ok" | "error", "error": str | null}],
         "total_price": int, "total_savings": int, "errors": [str]}

    Examples:
        - Use when: buyer says "دو تا بسته codm-80 و یکی codm-bp چقدر میشه؟"
        - Use when: verifying a cart before guiding the buyer to checkout
        - Don't use when: you only need one product's price (cpshop_get_product)
    """
    _reject_duplicate_ids(items)
    store = _load_store()
    lines = []
    errors: list[str] = []
    total_price = total_savings = item_count = 0

    for item in items:
        p = store.products.get(item.product_id)
        if p is None:
            err = (f"Unknown product id '{item.product_id}' — find valid ids with "
                   f"cpshop_search_products.")
            errors.append(err)
            lines.append({"product_id": item.product_id, "quantity": item.quantity,
                          "line_total": 0, "line_savings": 0, "status": "error", "error": err,
                          "title": None, "game": None, "unit_price": None})
            continue
        line_total = p["price"] * item.quantity
        savings = ((p["old"] - p["price"]) * item.quantity) if p["old"] else 0
        total_price += line_total
        total_savings += savings
        item_count += item.quantity
        lines.append({
            "product_id": p["id"], "title": p["title"], "game": p["game"],
            "quantity": item.quantity, "unit_price": p["price"],
            "line_total": line_total, "line_savings": savings,
            "status": "ok", "error": None,
        })

    payload = {
        "currency": store.currency,
        "line_count": len(lines),
        "item_count": item_count,
        "lines": lines,
        "total_price": total_price,
        "total_savings": total_savings,
        "errors": errors,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool(
    name="cpshop_store_stats",
    annotations={
        "title": "CP.Shop Store Statistics",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False,
    },
)
async def cpshop_store_stats(response_format: ResponseFormat = ResponseFormat.MARKDOWN) -> str:
    """Get catalog-wide statistics for the CP.Shop store.

    Summary of the whole catalog: product counts per category, price range,
    cheapest/most expensive products, discount stats, and support/delivery info.

    Args:
        response_format: 'markdown' for readable summary, 'json' for machine-readable.

    Returns:
        str: Stats. JSON schema:
        {"store": str, "currency": str, "total_products": int, "total_games": int,
         "categories": [{"key": str, "name_fa": str, "product_count": int}],
         "price_range": {"min": int, "max": int, "cheapest": {...}, "priciest": {...}},
         "discounted_products": int, "avg_discount_percent": int,
         "delivery": str, "support_hours": str}

    Examples:
        - Use when: "فروشگاه چی دار؟" / overview questions
        - Use when: comparing CP.Shop's range before searching specifics
    """
    store = _load_store()
    prods = store.product_list
    prices = [p["price"] for p in prods]
    cheapest = min(prods, key=lambda p: p["price"])
    priciest = max(prods, key=lambda p: p["price"])
    discounted = [p for p in prods if p["old"]]
    avg_disc = round(sum((1 - p["price"] / p["old"]) * 100 for p in discounted) / len(discounted)) if discounted else 0

    cats = []
    for key, c in store.categories.items():
        cats.append({"key": key, "name_fa": c["fa"],
                     "product_count": sum(1 for p in prods if p["cat"] == key)})

    payload = {
        "store": store.meta["name"],
        "currency": store.currency,
        "total_products": len(prods),
        "total_games": len(store.games),
        "categories": cats,
        "price_range": {
            "min": min(prices), "max": max(prices),
            "cheapest": _product_brief(cheapest, store),
            "priciest": _product_brief(priciest, store),
        },
        "discounted_products": len(discounted),
        "avg_discount_percent": avg_disc,
        "delivery": store.meta["delivery"],
        "support_hours": store.meta["support_hours"],
    }
    if response_format == ResponseFormat.JSON:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    return "\n".join([
        f"# {payload['store']} — آمار فروشگاه",
        f"- محصولات: **{payload['total_products']}** در {payload['total_games']} بازی",
        "- دسته‌ها: " + "، ".join(f"{c['name_fa']} ({c['product_count']})" for c in cats),
        f"- ارزان‌ترین: {payload['price_range']['cheapest']['title']} — {_toman(payload['price_range']['min'])}",
        f"- گران‌ترین: {payload['price_range']['priciest']['title']} — {_toman(payload['price_range']['max'])}",
        f"- محصولات تخفیف‌دار: {payload['discounted_products']} (میانگین تخفیف {avg_disc}٪)",
        f"- تحویل: {payload['delivery']} — پشتیبانی: {payload['support_hours']}",
    ])


if __name__ == "__main__":
    mcp.run()

#!/usr/bin/env python3
"""End-to-end test: drives the real MCP server over stdio JSON-RPC.

Starts `cpshop_mcp.py` as a subprocess, performs a full MCP lifecycle
(initialize -> initialized -> tools/list -> tools/call x N) and asserts
protocol + business behavior. Exits non-zero on any failure.
"""

import json
import subprocess
import sys
from pathlib import Path

# Windows consoles default to cp1252 and crash printing Persian tool output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)
SERVER = HERE / "cpshop_mcp.py"

next_id = 0


def rpc(proc, method, params=None, notify=False):
    global next_id
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if not notify:
        next_id += 1
        msg["id"] = next_id
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()
    if notify:
        return None
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"server closed stdout while waiting for {method}")
        resp = json.loads(line)
        if resp.get("id") == next_id:
            return resp


def main():
    proc = subprocess.Popen(
        [str(PYTHON), str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, ok, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))

    try:
        # ---- Lifecycle ----
        init = rpc(proc, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cpshop-test", "version": "1.0"},
        })
        info = init["result"]
        check("initialize: server name", info["serverInfo"]["name"] == "cpshop_mcp", str(info["serverInfo"]))
        check("initialize: tools capability", "tools" in info["capabilities"])

        rpc(proc, "notifications/initialized", {}, notify=True)

        # ---- tools/list ----
        tl = rpc(proc, "tools/list")
        tools = {t["name"] for t in tl["result"]["tools"]}
        expected = {"cpshop_list_games", "cpshop_search_products", "cpshop_get_product",
                    "cpshop_estimate_cart", "cpshop_store_stats"}
        check("tools/list: all 5 tools", expected <= tools, str(tools))
        schemas_ok = all("inputSchema" in t and t["inputSchema"].get("type") == "object"
                         for t in tl["result"]["tools"])
        check("tools/list: inputSchemas present", schemas_ok)
        ann_ok = all(t.get("annotations", {}).get("readOnlyHint") is True for t in tl["result"]["tools"])
        check("tools/list: readOnlyHint annotations", ann_ok)

        # ---- tools/call: list_games (JSON) ----
        r = rpc(proc, "tools/call", {"name": "cpshop_list_games",
                                     "arguments": {"response_format": "json"}})
        data = json.loads(r["result"]["content"][0]["text"])
        check("list_games: 16 games", data["total_games"] == 16, str(data["total_games"]))
        check("list_games: 37 products", data["total_products"] == 37, str(data["total_products"]))
        codm = next(g for g in data["games"] if g["key"] == "codm")
        check("list_games: codm count=5", codm["product_count"] == 5, str(codm))

        # ---- tools/call: search 'fortnite' (latin) ----
        r = rpc(proc, "tools/call", {"name": "cpshop_search_products",
                                     "arguments": {"query": "fortnite", "response_format": "json"}})
        data = json.loads(r["result"]["content"][0]["text"])
        check("search 'fortnite': 3 hits", data["total"] == 3, str(data["total"]))
        check("search 'fortnite': ids", {p["id"] for p in data["products"]} == {"fn-vbucks1", "fn-vbucks2", "fn-crew"})

        # ---- tools/call: search persian 'فورتنایت' ----
        r = rpc(proc, "tools/call", {"name": "cpshop_search_products",
                                     "arguments": {"query": "فورتنایت", "response_format": "json"}})
        data = json.loads(r["result"]["content"][0]["text"])
        check("search 'فورتنایت': 3 hits", data["total"] == 3, str(data["total"]))

        # ---- pagination ----
        r = rpc(proc, "tools/call", {"name": "cpshop_search_products",
                                     "arguments": {"query": "clash", "limit": 2, "offset": 0,
                                                   "response_format": "json"}})
        p1 = json.loads(r["result"]["content"][0]["text"])
        r = rpc(proc, "tools/call", {"name": "cpshop_search_products",
                                     "arguments": {"query": "clash", "limit": 2, "offset": 2,
                                                   "response_format": "json"}})
        p2 = json.loads(r["result"]["content"][0]["text"])
        check("pagination: has_more + next_offset", p1["has_more"] is True and p1["next_offset"] == 2)
        check("pagination: pages disjoint", p1["total"] == p2["total"] > p2["count"]
              and {p["id"] for p in p1["products"]}.isdisjoint({p["id"] for p in p2["products"]}))

        # ---- tools/call: get_product + error path ----
        r = rpc(proc, "tools/call", {"name": "cpshop_get_product", "arguments": {"product_id": "gift-steam"}})
        data = json.loads(r["result"]["content"][0]["text"])
        check("get_product: id field label", data["required_account_field"]["label_fa"].startswith("ایمیل"), )
        check("get_product: price", data["price"] == 810000, str(data["price"]))

        r = rpc(proc, "tools/call", {"name": "cpshop_get_product", "arguments": {"product_id": "nope-123"}})
        err_text = r["result"]["content"][0]["text"]
        check("get_product: unknown id -> actionable error",
              r["result"].get("isError") is not True and err_text.startswith("Error:") and "cpshop_search_products" in err_text)

        # ---- tools/call: estimate_cart mixed (ok + unknown + savings) ----
        cart = {"items": [
            {"product_id": "codm-80", "quantity": 2},
            {"product_id": "codm-bp", "quantity": 1},
            {"product_id": "fake-id", "quantity": 1},
        ]}
        r = rpc(proc, "tools/call", {"name": "cpshop_estimate_cart", "arguments": cart})
        data = json.loads(r["result"]["content"][0]["text"])
        lines = {l["product_id"]: l for l in data["lines"]}
        expected_total = 65000 * 2 + 340000
        check("cart: total price exact", data["total_price"] == expected_total,
              f"{data['total_price']} != {expected_total}")
        check("cart: item_count=3", data["item_count"] == 3)
        check("cart: unknown id flagged per-line", lines["fake-id"]["status"] == "error" and "cpshop_search_products" in lines["fake-id"]["error"])
        check("cart: savings computed (old>price)", data["total_savings"] == (72000 - 65000) * 2,
              str(data["total_savings"]))
        check("cart: errors list populated", len(data["errors"]) == 1)

        # ---- schema validation: duplicate ids rejected, qty bounds ----
        r = rpc(proc, "tools/call", {"name": "cpshop_estimate_cart",
                                     "arguments": {"items": [{"product_id": "codm-80", "quantity": 1},
                                                              {"product_id": "codm-80", "quantity": 2}]}})
        dup = r["result"]["content"][0]["text"] + str(r.get("result", {}).get("isError", False))
        check("cart: duplicate ids rejected", "Duplicate product_id" in dup)
        r = rpc(proc, "tools/call", {"name": "cpshop_estimate_cart",
                                     "arguments": {"items": [{"product_id": "codm-80", "quantity": 500}]}})
        check("cart: quantity 500 rejected", r["result"].get("isError") is True or "quantity" in r["result"]["content"][0]["text"].lower())

        # ---- store_stats ----
        r = rpc(proc, "tools/call", {"name": "cpshop_store_stats", "arguments": {"response_format": "json"}})
        data = json.loads(r["result"]["content"][0]["text"])
        check("stats: totals", data["total_products"] == 37 and data["total_games"] == 16)
        check("stats: cheapest is codm-80", data["price_range"]["cheapest"]["id"] == "codm-80")
        check("stats: delivery text", "تحویل" in data["delivery"])

    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=10)
        err = proc.stderr.read().decode(errors="replace")

    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    if err.strip():
        print("--- server stderr (tail) ---")
        print("\n".join(err.strip().splitlines()[-5:]))
    if failed:
        sys.exit(1)
    print("ALL LIFECYCLE CHECKS PASSED")


if __name__ == "__main__":
    main()

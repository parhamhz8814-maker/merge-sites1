import sys

print('python_executable:', sys.executable)

# 1) imports
import store_db
import cpshop_mcp
import cpshop_http
import security

print('imports: OK')

# 2) DB + order create/pay smoke test
store_db.init_db(seed=True)
items = [
    {"product_id": "codm-80", "quantity": 2, "player_id": "12345678"},
]
order = store_db.create_order(items)
print('create_order:', order)

# payment should require pay_token
pay = store_db.pay_order(order['tracking'], order['pay_token'])
print('pay_order:', pay)

got = store_db.get_order(order['tracking'])
print('get_order:', got)

assert got is not None
assert got['status'] == 'paid'
assert got['total'] == order['total']
print('order flow: OK')

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

# pick a real product id from the seeded catalog
with store_db._connect() as conn:
    row = conn.execute(
        "SELECT id FROM products WHERE category='codm' AND is_active=1 LIMIT 1"
    ).fetchone()
pid = row['id']

items = [{"product_id": pid, "quantity": 2, "player_id": "12345678"}]
order = store_db.create_order(
    items,
    customer_name="Ali Rezaei",
    customer_contact="09121234567",
)
print('create_order:', order)

# payment should require pay_token
pay = store_db.pay_order(order['tracking'], order['pay_token'])
print('pay_order:', pay)

# anonymous read masks contact; token read reveals it
anon = store_db.get_order(order['tracking'])
owned = store_db.get_order(order['tracking'], order['pay_token'])
print('get_order (anon):', anon)
print('get_order (owner):', owned)

assert owned is not None
assert owned['status'] == 'paid'
assert owned['total'] == order['total']
assert anon['customer_name'] is None, "contact must be masked without token"
assert owned['customer_contact'] == "09121234567"
print('order flow: OK')

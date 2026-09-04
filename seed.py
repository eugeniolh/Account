"""
seed.py — one-time setup: creates the DB and loads your known accounts,
recurring items, and a starter set of category rules. Run this once:

    python3 seed.py

Safe to re-run: uses upserts / INSERT OR IGNORE where it matters.
"""

from db import init_db, get_conn, update_account_balance, upsert_rule

init_db()
conn = get_conn()

# --- accounts (live cash inputs; replace with real balances any time) ---
update_account_balance(conn, "Santander UK", 3405.92, "GBP")
update_account_balance(conn, "Santander ES", 114.79, "GBP")  # already converted to GBP
update_account_balance(conn, "Amex UK", -3191.00, "GBP")

# --- recurring items (from your existing forecast) ---
recurring = [
    ("Salary", "Income", 6200, 1),
    ("Rent", "Expense", -2275, 5),
    ("Electricity", "Expense", -40, 5),
    ("Gas", "Expense", -60, 5),
    ("Council tax", "Expense", -95, 10),
    ("Internet", "Expense", -40, 19),
    ("BA credit card rebate", "Income", 235, 25),
    ("Three mobile", "Expense", -8, 27),
    ("Lendwise loan repayment", "Expense", -352, 30),
    ("TFL", "Expense", -110, None),
]
cur = conn.cursor()
for name, typ, amount, day in recurring:
    cur.execute("SELECT id FROM recurring_items WHERE name = %s", (name,))
    existing = cur.fetchone()
    if not existing:
        cur.execute(
            "INSERT INTO recurring_items (name, type, amount, day_of_month, active) VALUES (%s, %s, %s, %s, 'Y')",
            (name, typ, amount, day),
        )
conn.commit()
cur.close()

# --- starter category rules (your "prior instructions") ---
starter_rules = {
    "salary": "Income",
    "rent": "Housing",
    "electricity": "Utilities",
    "gas": "Utilities",
    "council tax": "Utilities",
    "internet": "Utilities",
    "three": "Phone",
    "lendwise": "Loan repayment",
    "tfl": "Transport",
    "ba ": "Rebate / Credit",
    "spotify": "Subscriptions",
    "amazon": "Shopping",
    "tesco": "Groceries",
    "sainsbury": "Groceries",
    "uber": "Transport",
}
for pattern, category in starter_rules.items():
    upsert_rule(conn, pattern, category)

conn.close()
print("Seeded the hosted Postgres database successfully.")

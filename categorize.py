"""
categorize.py — applies your saved category rules to any uncategorized
transactions. This runs automatically every time the app loads new data.

Matching is a simple case-insensitive substring match: if a rule's pattern
appears anywhere in the transaction's item text, that rule's category wins.
The first matching rule (by rule id) is used. This is intentionally simple
so it stays predictable and easy to reason about — you can always see every
rule on the Categorize page.
"""


def apply_categorization(conn):
    """Auto-categorize any transaction with a NULL category using saved rules.
    Returns the number of transactions that were auto-categorized."""
    cur = conn.cursor()
    cur.execute("SELECT pattern, category FROM category_rules ORDER BY id")
    rules = cur.fetchall()
    if not rules:
        cur.close()
        return 0

    cur.execute("SELECT id, item FROM transactions WHERE category IS NULL")
    uncategorized = cur.fetchall()

    matched = 0
    for tx in uncategorized:
        item_lower = tx["item"].lower()
        for rule in rules:
            if rule["pattern"] in item_lower:
                cur.execute(
                    "UPDATE transactions SET category = %s WHERE id = %s",
                    (rule["category"], tx["id"]),
                )
                matched += 1
                break
    conn.commit()
    cur.close()
    return matched


def get_uncategorized(conn):
    from db import df
    return df(
        conn,
        "SELECT id, date, bank_account, item, amount FROM transactions "
        "WHERE category IS NULL ORDER BY date DESC",
    )


def get_known_categories(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT category AS cat FROM transactions WHERE category IS NOT NULL "
        "UNION SELECT DISTINCT category AS cat FROM category_rules ORDER BY 1"
    )
    rows = cur.fetchall()
    cur.close()
    return [r["cat"] for r in rows if r["cat"]]

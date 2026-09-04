"""
forecast.py — live cash, 5-month forward cash flow forecast, and the
actual-vs-expected "bridge" that surfaces unplanned income/expenses.

Also excludes, from a given month's forecast, any recurring/extraordinary
item that already has a matching actual transaction in that month — since
that money movement is already reflected in the live cash balance (BoP),
counting it again in the forecast would double-count it.
"""

from datetime import date
import calendar


def month_end(d: date) -> date:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)


def add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def get_live_cash(conn) -> float:
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(latest_balance), 0) AS total FROM accounts")
    row = cur.fetchone()
    cur.close()
    return float(row["total"] or 0.0)


def get_active_recurring(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, type, amount FROM recurring_items WHERE active = 'Y'")
    rows = cur.fetchall()
    cur.close()
    return rows


def get_extraordinary_in_month(conn, month_start: date, month_stop: date):
    cur = conn.cursor()
    cur.execute(
        "SELECT description, amount FROM extraordinary_items "
        "WHERE date >= %s AND date <= %s",
        (month_start.isoformat(), month_stop.isoformat()),
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _matched_items_this_window(conn, month_start: date, month_stop: date, recurring, extra_rows):
    """Finds which recurring items and which extraordinary items already have
    a matching actual transaction inside this date window. Used so an item
    that has already happened (and is therefore already reflected in the
    live cash balance) isn't ALSO added as a forecasted amount for that same
    month — that would double-count it."""
    cur = conn.cursor()
    cur.execute(
        "SELECT item FROM transactions WHERE date >= %s AND date <= %s",
        (month_start.isoformat(), month_stop.isoformat()),
    )
    txs = cur.fetchall()
    cur.close()
    item_texts = [t["item"].lower() for t in txs]

    matched_recurring_names = set()
    for r in recurring:
        name = r["name"].lower()
        if any(name in it or it in name for it in item_texts):
            matched_recurring_names.add(r["name"])

    matched_extra_descs = set()
    for r in extra_rows:
        desc = r["description"].lower()
        if any(desc in it or it in desc for it in item_texts):
            matched_extra_descs.add(r["description"])

    return matched_recurring_names, matched_extra_descs


def forecast_5_months(conn, today: date = None):
    """Returns a list of dicts: month_label, month_end, bop, recurring_total,
    extraordinary_total, net_change, eop.

    For any month that already has actual transactions matching a recurring
    or extraordinary item, that item's forecasted amount is excluded for
    that month — it's already happened and is already inside the live cash
    balance (BoP), so forecasting it again would double-count it.
    """
    if today is None:
        today = date.today()

    recurring = get_active_recurring(conn)

    results = []
    bop = get_live_cash(conn)
    cursor = date(today.year, today.month, 1)

    for i in range(6):  # today's month + 5 forward
        m_start = cursor
        m_end = month_end(cursor)
        extra_rows = get_extraordinary_in_month(conn, m_start, m_end)

        matched_recurring, matched_extra = _matched_items_this_window(
            conn, m_start, m_end, recurring, extra_rows
        )

        # only forecast the items that HAVEN'T already happened this month
        recurring_total = sum(r["amount"] for r in recurring if r["name"] not in matched_recurring)
        extra_total = sum(r["amount"] for r in extra_rows if r["description"] not in matched_extra)

        already_happened_total = (
            sum(r["amount"] for r in recurring if r["name"] in matched_recurring)
            + sum(r["amount"] for r in extra_rows if r["description"] in matched_extra)
        )

        net_change = recurring_total + extra_total
        eop = bop + net_change

        results.append({
            "month_label": m_start.strftime("%b-%y"),
            "month_end": m_end,
            "bop": bop,
            "recurring_total": recurring_total,
            "extraordinary_total": extra_total,
            "extraordinary_items": [dict(r) for r in extra_rows],
            "already_happened_total": already_happened_total,
            "matched_recurring": sorted(matched_recurring),
            "matched_extraordinary": sorted(matched_extra),
            "net_change": net_change,
            "eop": eop,
        })

        bop = eop
        cursor = add_months(cursor, 1)

    return results


def actual_vs_expected(conn, month_start: date, month_stop: date):
    """For a given month, split actual transactions into:
      - matched: item text matches an active recurring item name, or matches
        a logged extraordinary item in the same window
      - unexpected: everything else, split into income (amount > 0) and
        expense (amount < 0)
    Returns dict with 'unexpected_income', 'unexpected_expense' (both lists)
    and their totals.
    """
    recurring_names = [r["name"].lower() for r in get_active_recurring(conn)]
    extra_rows = get_extraordinary_in_month(conn, month_start, month_stop)
    extra_descs = [r["description"].lower() for r in extra_rows]

    cur = conn.cursor()
    cur.execute(
        "SELECT id, date, bank_account, item, amount, category FROM transactions "
        "WHERE date >= %s AND date <= %s ORDER BY date",
        (month_start.isoformat(), month_stop.isoformat()),
    )
    txs = cur.fetchall()
    cur.close()

    unexpected_income = []
    unexpected_expense = []

    for tx in txs:
        item_lower = tx["item"].lower()
        is_recurring_match = any(name in item_lower or item_lower in name for name in recurring_names)
        is_extra_match = any(desc in item_lower or item_lower in desc for desc in extra_descs)

        if is_recurring_match or is_extra_match:
            continue  # this was expected, skip

        row = dict(tx)
        if tx["amount"] >= 0:
            unexpected_income.append(row)
        else:
            unexpected_expense.append(row)

    return {
        "unexpected_income": unexpected_income,
        "unexpected_income_total": sum(r["amount"] for r in unexpected_income),
        "unexpected_expense": unexpected_expense,
        "unexpected_expense_total": sum(r["amount"] for r in unexpected_expense),
    }

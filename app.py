"""
app.py — Net Worth / Cash Flow dashboard.

Run with:
    streamlit run app.py

On every load, new transactions are auto-categorized against your saved
rules. Anything left uncategorized blocks a banner on the Dashboard and
is queued up on the Categorize page.
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
import plotly.graph_objects as go

from db import init_db, get_conn, upsert_rule, set_transaction_category, add_transaction, update_account_balance, df
from categorize import apply_categorization, get_uncategorized, get_known_categories
from forecast import forecast_5_months, actual_vs_expected, month_end, get_live_cash
import import_statements as stmt

st.set_page_config(page_title="Net Worth Tracker", layout="wide")
init_db()
conn = get_conn()

# Auto-categorize on every load
newly_matched = apply_categorization(conn)

# ---------------------------------------------------------------------
PAGE = st.sidebar.radio(
    "Navigate",
    ["Dashboard", "Import Statements", "Categorize", "Transactions", "Recurring Items", "Extraordinary Items", "Accounts"],
)

uncategorized_df = get_uncategorized(conn)
n_uncat = len(uncategorized_df)

if n_uncat > 0:
    st.sidebar.warning(f"⚠️ {n_uncat} transaction(s) need categorizing")

# ---------------------------------------------------------------------
if PAGE == "Dashboard":
    st.title("Net Worth Tracker")

    if n_uncat > 0:
        st.info(f"You have **{n_uncat}** uncategorized transaction(s). "
                f"Go to the **Categorize** page to clear them — the forecast "
                f"below still works, but the actual-vs-expected view will be incomplete "
                f"until they're categorized.")

    live_cash = get_live_cash(conn)
    forecast = forecast_5_months(conn)

    col1, col2, col3 = st.columns(3)
    col1.metric("Live Cash (all accounts)", f"£{live_cash:,.0f}")
    col2.metric(f"Expected EoM {forecast[0]['month_end'].strftime('%b')}", f"£{forecast[0]['eop']:,.0f}",
                delta=f"£{forecast[0]['net_change']:,.0f}")
    col3.metric(f"Expected EoM {forecast[5]['month_end'].strftime('%b')} (5mo out)", f"£{forecast[5]['eop']:,.0f}")

    st.subheader("5-Month Cash Forecast")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[f["month_label"] for f in forecast],
        y=[f["eop"] for f in forecast],
        mode="lines+markers+text",
        text=[f"£{f['eop']:,.0f}" for f in forecast],
        textposition="top center",
        line=dict(width=3),
    ))
    fig.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20), yaxis_title="GBP")
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Forecast detail (recurring + extraordinary by month)"):
        detail_rows = []
        for f in forecast:
            detail_rows.append({
                "Month": f["month_label"],
                "BoP Cash": f["bop"],
                "Recurring Net": f["recurring_total"],
                "Extraordinary Net": f["extraordinary_total"],
                "Already Happened (excluded)": f["already_happened_total"],
                "EoP Cash": f["eop"],
            })
        st.dataframe(pd.DataFrame(detail_rows).style.format({
            "BoP Cash": "£{:,.0f}", "Recurring Net": "£{:,.0f}",
            "Extraordinary Net": "£{:,.0f}", "Already Happened (excluded)": "£{:,.0f}",
            "EoP Cash": "£{:,.0f}",
        }), use_container_width=True, hide_index=True)

        current = forecast[0]
        if current["matched_recurring"] or current["matched_extraordinary"]:
            st.caption(
                "Excluded from this month's forecast because they've already happened "
                "(and are already inside your live cash balance): "
                + ", ".join(current["matched_recurring"] + current["matched_extraordinary"])
            )

    st.subheader("Actual vs. Expected — this month's surprises")
    today = date.today()
    m_start = date(today.year, today.month, 1)
    m_stop = month_end(today)
    bridge = actual_vs_expected(conn, m_start, m_stop)

    bcol1, bcol2 = st.columns(2)
    with bcol1:
        st.markdown(f"**Unexpected Income** — £{bridge['unexpected_income_total']:,.2f}")
        if bridge["unexpected_income"]:
            st.dataframe(pd.DataFrame(bridge["unexpected_income"])[["date", "bank_account", "item", "amount", "category"]],
                         use_container_width=True, hide_index=True)
        else:
            st.caption("No unexpected income this month.")
    with bcol2:
        st.markdown(f"**Unexpected Expenses** — £{bridge['unexpected_expense_total']:,.2f}")
        if bridge["unexpected_expense"]:
            st.dataframe(pd.DataFrame(bridge["unexpected_expense"])[["date", "bank_account", "item", "amount", "category"]],
                         use_container_width=True, hide_index=True)
        else:
            st.caption("No unexpected expenses this month.")

elif PAGE == "Import Statements":
    st.title("Import Statements")
    st.caption(
        f"Download a transaction export (CSV) from your bank's website and save it into "
        f"`{stmt.INCOMING_DIR}`. This page picks up anything sitting there."
    )

    known_accounts = [r["name"] for r in df(conn, "SELECT name FROM accounts ORDER BY name").to_dict("records")]
    incoming_files = stmt.list_incoming_files()

    if not incoming_files:
        st.info("No files waiting. Drop a CSV export into the folder above, then refresh this page.")
    else:
        for filepath in incoming_files:
            with st.container(border=True):
                st.subheader(filepath.name)
                columns, sample = stmt.preview_columns(filepath)
                st.dataframe(sample, use_container_width=True, hide_index=True)

                account_choice = st.selectbox(
                    "Which account is this statement from?",
                    options=known_accounts + ["+ New account..."],
                    key=f"acct_{filepath.name}",
                )
                if account_choice == "+ New account...":
                    account_choice = st.text_input("New account name", key=f"newacct_{filepath.name}")

                if not account_choice:
                    continue

                profile = stmt.get_profile(conn, account_choice)

                if profile is None:
                    st.markdown(f"**First import for '{account_choice}' — map the columns once:**")
                    c1, c2 = st.columns(2)
                    date_col = c1.selectbox("Date column", columns, key=f"date_{filepath.name}")
                    item_col = c2.selectbox("Description column", columns, key=f"item_{filepath.name}")
                    date_format = c1.text_input(
                        "Date format (leave blank to auto-detect, e.g. %d/%m/%Y)",
                        key=f"fmt_{filepath.name}",
                    )
                    amount_mode = c2.radio(
                        "Amount layout", ["Single amount column", "Separate debit/credit columns"],
                        key=f"mode_{filepath.name}",
                    )

                    if amount_mode == "Single amount column":
                        amount_col = c1.selectbox("Amount column", columns, key=f"amtcol_{filepath.name}")
                        amount_sign = c2.radio(
                            "Sign convention", ["as_is (negative = expense)", "flip (positive = expense)"],
                            key=f"sign_{filepath.name}",
                        )
                        sign_value = "flip" if amount_sign.startswith("flip") else "as_is"
                        debit_col = credit_col = None
                        mode_value = "single"
                    else:
                        debit_col = c1.selectbox("Debit column", columns, key=f"debit_{filepath.name}")
                        credit_col = c2.selectbox("Credit column", columns, key=f"credit_{filepath.name}")
                        amount_col = None
                        sign_value = "as_is"
                        mode_value = "debit_credit"

                    if st.button("Save mapping & preview", key=f"savemap_{filepath.name}"):
                        stmt.save_profile(
                            conn, account_choice, date_col, item_col, mode_value,
                            amount_col=amount_col, amount_sign=sign_value,
                            debit_col=debit_col, credit_col=credit_col,
                            date_format=date_format or None,
                        )
                        st.rerun()
                else:
                    try:
                        parsed = stmt.parse_file(filepath, profile)
                        st.markdown(f"**Ready to import** — {len(parsed)} row(s) parsed using the saved mapping for '{account_choice}':")
                        st.dataframe(parsed.head(10), use_container_width=True, hide_index=True)

                        cimp, cmap = st.columns(2)
                        if cimp.button("Import this file", key=f"import_{filepath.name}"):
                            imported, skipped = stmt.import_parsed(conn, account_choice, parsed)
                            stmt.archive_file(filepath)
                            apply_categorization(conn)
                            st.success(f"Imported {imported} new transaction(s), skipped {skipped} already-logged duplicate(s).")
                            st.rerun()
                        if cmap.button("Re-map columns for this account", key=f"remap_{filepath.name}"):
                            cur = conn.cursor()
                            cur.execute("DELETE FROM import_profiles WHERE bank_account = %s", (account_choice,))
                            conn.commit()
                            cur.close()
                            st.rerun()
                    except Exception as e:
                        st.error(f"Couldn't parse this file with the saved mapping: {e}")
                        if st.button("Re-map columns for this account", key=f"remap2_{filepath.name}"):
                            cur = conn.cursor()
                            cur.execute("DELETE FROM import_profiles WHERE bank_account = %s", (account_choice,))
                            conn.commit()
                            cur.close()
                            st.rerun()

# ---------------------------------------------------------------------
elif PAGE == "Categorize":
    st.title("Categorize Transactions")
    st.caption("Assign a category to each item below. Your choice is saved as a rule, "
               "so matching items are categorized automatically from now on.")

    uncategorized_df = get_uncategorized(conn)
    if uncategorized_df.empty:
        st.success("Nothing to categorize — you're all caught up.")
    else:
        known_categories = get_known_categories(conn) or ["Uncategorized"]
        st.write(f"**{len(uncategorized_df)}** transaction(s) awaiting a category:")

        for _, row in uncategorized_df.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 2])
                c1.write(f"**{row['item']}**  \n{row['date']} · {row['bank_account']} · £{row['amount']:,.2f}")
                choice = c2.selectbox(
                    "Category", options=known_categories + ["+ New category..."],
                    key=f"cat_{row['id']}", label_visibility="collapsed",
                )
                if choice == "+ New category...":
                    choice = c2.text_input("New category name", key=f"newcat_{row['id']}")
                if c3.button("Save", key=f"save_{row['id']}"):
                    if choice:
                        set_transaction_category(conn, row["id"], choice)
                        # learn a rule from a meaningful keyword in the item text
                        keyword = row["item"].split()[0].lower()
                        upsert_rule(conn, keyword, choice)
                        st.rerun()

# ---------------------------------------------------------------------
elif PAGE == "Transactions":
    st.title("Transactions")

    with st.expander("➕ Add a transaction manually"):
        with st.form("add_tx"):
            c1, c2, c3, c4 = st.columns(4)
            t_date = c1.date_input("Date", value=date.today())
            t_account = c2.text_input("Bank account", value="Santander UK")
            t_item = c3.text_input("Item / description")
            t_amount = c4.number_input("Amount (+income / -expense)", step=1.0, format="%.2f")
            submitted = st.form_submit_button("Add")
            if submitted and t_item:
                add_transaction(conn, t_date.isoformat(), t_account, t_item, t_amount)
                st.success("Added.")
                st.rerun()

    with st.expander("📤 Import from CSV (columns: date, bank_account, item, amount)"):
        uploaded = st.file_uploader("Choose CSV", type="csv")
        if uploaded is not None:
            new_tx = pd.read_csv(uploaded)
            required = {"date", "bank_account", "item", "amount"}
            if not required.issubset(set(c.lower() for c in new_tx.columns)):
                st.error(f"CSV must have columns: {', '.join(required)}")
            else:
                new_tx.columns = [c.lower() for c in new_tx.columns]
                for _, r in new_tx.iterrows():
                    add_transaction(conn, str(r["date"]), r["bank_account"], r["item"], float(r["amount"]))
                st.success(f"Imported {len(new_tx)} transaction(s). Re-categorizing...")
                apply_categorization(conn)
                st.rerun()

    st.subheader("Full ledger")
    all_tx = df(conn, "SELECT date, bank_account, item, amount, category FROM transactions ORDER BY date DESC")
    st.dataframe(all_tx, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------
elif PAGE == "Recurring Items":
    st.title("Recurring Items")
    st.caption("Your regular monthly income and bills. Toggle Active instead of deleting rows.")

    items_df = df(conn, "SELECT id, name, type, amount, day_of_month, active, category FROM recurring_items ORDER BY id")
    edited = st.data_editor(
        items_df, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "type": st.column_config.SelectboxColumn(options=["Income", "Expense"]),
            "active": st.column_config.SelectboxColumn(options=["Y", "N"]),
        },
    )
    if st.button("Save changes", key="save_recurring"):
        cur = conn.cursor()
        cur.execute("DELETE FROM recurring_items")
        for _, r in edited.iterrows():
            if pd.notna(r.get("name")):
                cur.execute(
                    "INSERT INTO recurring_items (name, type, amount, day_of_month, active, category) VALUES (%s, %s, %s, %s, %s, %s)",
                    (r["name"], r["type"], r["amount"], r.get("day_of_month"), r.get("active", "Y"), r.get("category")),
                )
        conn.commit()
        cur.close()
        st.success("Saved.")
        st.rerun()

# ---------------------------------------------------------------------
elif PAGE == "Extraordinary Items":
    st.title("Extraordinary Items")
    st.caption("One-off income/expenses. Picked up automatically by the forecast for the month they fall in.")

    items_df = df(conn, "SELECT id, date, description, amount, category FROM extraordinary_items ORDER BY date DESC")
    edited = st.data_editor(items_df, num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("Save changes", key="save_extra"):
        cur = conn.cursor()
        cur.execute("DELETE FROM extraordinary_items")
        for _, r in edited.iterrows():
            if pd.notna(r.get("description")):
                cur.execute(
                    "INSERT INTO extraordinary_items (date, description, amount, category) VALUES (%s, %s, %s, %s)",
                    (str(r["date"]), r["description"], r["amount"], r.get("category")),
                )
        conn.commit()
        cur.close()
        st.success("Saved.")
        st.rerun()

# ---------------------------------------------------------------------
elif PAGE == "Accounts":
    st.title("Accounts")
    st.caption("These balances feed 'Live Cash' on the Dashboard. Update them here until a live bank feed is wired up.")

    accounts_df = df(conn, "SELECT id, name, currency, latest_balance, last_updated FROM accounts ORDER BY id")
    edited = st.data_editor(
        accounts_df, num_rows="dynamic", use_container_width=True, hide_index=True,
        disabled=["last_updated"],
    )
    if st.button("Save changes", key="save_accounts"):
        for _, r in edited.iterrows():
            if pd.notna(r.get("name")):
                update_account_balance(conn, r["name"], r["latest_balance"], r.get("currency", "GBP"))
        st.success("Saved.")
        st.rerun()

conn.close()

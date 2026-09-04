"""
import_statements.py — reads bank statement CSVs you've manually downloaded
and dropped into statements_incoming/, maps their columns to our schema
(date, item, amount), dedupes against existing transactions, and archives
the file once imported.

Bank exports vary in column layout, so the FIRST file from a given bank
account needs a one-time column mapping (done in the app UI). That mapping
is saved in `import_profiles` and reused automatically for every later file
from that same account.
"""

import os
import shutil
import pandas as pd
from pathlib import Path
from datetime import datetime

INCOMING_DIR = Path(__file__).parent / "statements_incoming"
ARCHIVE_DIR = Path(__file__).parent / "statements_archive"
INCOMING_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)


def list_incoming_files():
    """CSV files sitting in statements_incoming/, ready to be imported."""
    return sorted([p for p in INCOMING_DIR.glob("*.csv")])


def preview_columns(filepath, n=5):
    """Returns (column_names, sample_dataframe) for the column-mapping UI."""
    raw = pd.read_csv(filepath, nrows=n)
    return list(raw.columns), raw


def get_profile(conn, bank_account):
    cur = conn.cursor()
    cur.execute("SELECT * FROM import_profiles WHERE bank_account = %s", (bank_account,))
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def save_profile(conn, bank_account, date_col, item_col, amount_mode,
                  amount_col=None, amount_sign="as_is",
                  debit_col=None, credit_col=None, date_format=None):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO import_profiles
           (bank_account, date_col, item_col, amount_mode, amount_col, amount_sign,
            debit_col, credit_col, date_format)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (bank_account) DO UPDATE SET
             date_col=EXCLUDED.date_col, item_col=EXCLUDED.item_col,
             amount_mode=EXCLUDED.amount_mode, amount_col=EXCLUDED.amount_col,
             amount_sign=EXCLUDED.amount_sign, debit_col=EXCLUDED.debit_col,
             credit_col=EXCLUDED.credit_col, date_format=EXCLUDED.date_format""",
        (bank_account, date_col, item_col, amount_mode, amount_col, amount_sign,
         debit_col, credit_col, date_format),
    )
    conn.commit()
    cur.close()


def parse_file(filepath, profile):
    """Applies a saved profile to a CSV file. Returns a DataFrame with
    columns: date (str, ISO), item (str), amount (float)."""
    raw = pd.read_csv(filepath)

    if profile["date_format"]:
        dates = pd.to_datetime(raw[profile["date_col"]], format=profile["date_format"])
    else:
        dates = pd.to_datetime(raw[profile["date_col"]], dayfirst=True)

    items = raw[profile["item_col"]].astype(str)

    if profile["amount_mode"] == "single":
        amounts = pd.to_numeric(raw[profile["amount_col"]], errors="coerce")
        if profile["amount_sign"] == "flip":
            amounts = -amounts
    else:  # debit_credit
        debit = pd.to_numeric(raw[profile["debit_col"]], errors="coerce").fillna(0)
        credit = pd.to_numeric(raw[profile["credit_col"]], errors="coerce").fillna(0)
        amounts = credit - debit  # debit reduces cash, credit increases it

    out = pd.DataFrame({
        "date": dates.dt.strftime("%Y-%m-%d"),
        "item": items,
        "amount": amounts,
    }).dropna(subset=["amount"])

    return out


def existing_transaction_keys(conn, bank_account):
    """Set of (date, item, amount) tuples already in the ledger for this
    account, used to skip re-importing the same statement twice."""
    cur = conn.cursor()
    cur.execute(
        "SELECT date, item, amount FROM transactions WHERE bank_account = %s",
        (bank_account,),
    )
    rows = cur.fetchall()
    cur.close()
    return {(r["date"], r["item"], round(float(r["amount"]), 2)) for r in rows}


def import_parsed(conn, bank_account, parsed_df):
    """Inserts new rows (skipping duplicates already in the ledger).
    Returns (imported_count, skipped_count)."""
    from db import add_transaction

    existing = existing_transaction_keys(conn, bank_account)
    imported, skipped = 0, 0

    for _, row in parsed_df.iterrows():
        key = (row["date"], row["item"], round(float(row["amount"]), 2))
        if key in existing:
            skipped += 1
            continue
        add_transaction(conn, row["date"], bank_account, row["item"], float(row["amount"]))
        existing.add(key)
        imported += 1

    return imported, skipped


def archive_file(filepath):
    dest = ARCHIVE_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{filepath.name}"
    shutil.move(str(filepath), str(dest))
    return dest

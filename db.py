"""
db.py — Postgres schema and data-access helpers for the Net Worth app.

Uses a HOSTED Postgres database (e.g. a free Supabase project) instead of a
local SQLite file, so the app works identically whether it's running on
your laptop or deployed to Streamlit Community Cloud — same data either way.

Connection string resolution order:
  1. st.secrets["DATABASE_URL"]   (set this in Streamlit Cloud's Secrets)
  2. os.environ["DATABASE_URL"]   (set this in a local .env file for dev)

Tables:
  accounts             one row per bank account, holds the latest known balance
  transactions          raw ledger: date, bank_account, item, amount, category
  category_rules        keyword -> category, grows every time you categorize
  recurring_items        monthly income/bills used in the forecast
  extraordinary_items    one-off income/expenses used in the forecast
"""

import os
import psycopg2
import psycopg2.extras

try:
    import streamlit as st
    _HAS_STREAMLIT = True
except ImportError:
    _HAS_STREAMLIT = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_database_url():
    if _HAS_STREAMLIT:
        try:
            if "DATABASE_URL" in st.secrets:
                return st.secrets["DATABASE_URL"]
        except Exception:
            pass  # no secrets.toml present (e.g. running plain python, not streamlit)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "No DATABASE_URL found. Set it in .streamlit/secrets.toml (Streamlit Cloud) "
            "or in a local .env file (DATABASE_URL=postgresql://...) for local runs."
        )
    return url


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    currency TEXT NOT NULL DEFAULT 'GBP',
    latest_balance REAL NOT NULL DEFAULT 0,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    date TEXT NOT NULL,
    bank_account TEXT NOT NULL,
    item TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT
);

CREATE TABLE IF NOT EXISTS category_rules (
    id SERIAL PRIMARY KEY,
    pattern TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recurring_items (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    day_of_month INTEGER,
    active TEXT NOT NULL DEFAULT 'Y',
    category TEXT
);

CREATE TABLE IF NOT EXISTS extraordinary_items (
    id SERIAL PRIMARY KEY,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT
);

CREATE TABLE IF NOT EXISTS import_profiles (
    bank_account TEXT PRIMARY KEY,
    date_col TEXT NOT NULL,
    item_col TEXT NOT NULL,
    amount_mode TEXT NOT NULL,        -- 'single' or 'debit_credit'
    amount_col TEXT,                  -- used when amount_mode = 'single'
    amount_sign TEXT DEFAULT 'as_is', -- 'as_is' or 'flip' (used when amount_mode = 'single')
    debit_col TEXT,                   -- used when amount_mode = 'debit_credit'
    credit_col TEXT,                  -- used when amount_mode = 'debit_credit'
    date_format TEXT                  -- e.g. '%d/%m/%Y', blank = auto-detect
);
"""


def get_conn():
    conn = psycopg2.connect(_get_database_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(SCHEMA)
    conn.commit()
    cur.close()
    conn.close()


def df(conn, query, params=()):
    """Runs a query and returns a pandas DataFrame. Deliberately avoids
    pd.read_sql_query with a raw psycopg2 connection — that combination is
    unsupported by pandas and silently garbles column data. Fetching rows
    via the cursor (RealDictCursor gives dict-like rows) and building the
    DataFrame directly is reliable."""
    import pandas as pd
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    return pd.DataFrame([dict(r) for r in rows])


def upsert_rule(conn, pattern, category):
    pattern = pattern.strip().lower()
    if not pattern:
        return
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO category_rules (pattern, category) VALUES (%s, %s) "
        "ON CONFLICT (pattern) DO UPDATE SET category = EXCLUDED.category",
        (pattern, category),
    )
    conn.commit()
    cur.close()


def set_transaction_category(conn, tx_id, category):
    cur = conn.cursor()
    cur.execute("UPDATE transactions SET category = %s WHERE id = %s", (category, tx_id))
    conn.commit()
    cur.close()


def add_transaction(conn, tx_date, bank_account, item, amount, category=None):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO transactions (date, bank_account, item, amount, category) VALUES (%s, %s, %s, %s, %s)",
        (tx_date, bank_account, item, amount, category),
    )
    conn.commit()
    cur.close()


def update_account_balance(conn, name, balance, currency="GBP"):
    from datetime import datetime
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO accounts (name, currency, latest_balance, last_updated) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (name) DO UPDATE SET latest_balance = EXCLUDED.latest_balance, "
        "currency = EXCLUDED.currency, last_updated = EXCLUDED.last_updated",
        (name, currency, balance, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    cur.close()

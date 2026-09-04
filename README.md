# Net Worth Tracker

A dashboard for live cash, a 5-month forward forecast, and an
actual-vs-expected view that surfaces unplanned income/expenses —
accessible from your iPhone (or anywhere) once deployed.

Data lives in a hosted Postgres database (free tier via Supabase), so the
app works identically whether it's running on your laptop or deployed to
Streamlit Community Cloud.

## 1. Create a free hosted database (Supabase)

1. Go to [supabase.com](https://supabase.com), sign up free, create a new project.
2. Once it's ready: **Project Settings → Database → Connection string → URI**.
   Use the **Session pooler** connection string (it's IPv4-compatible, which
   Streamlit Cloud needs) — it looks like:
   ```
   postgresql://postgres.xxxxxxxx:[YOUR-PASSWORD]@aws-0-eu-west-2.pooler.supabase.com:5432/postgres
   ```
3. Copy it — you'll paste it in two places below.

## 2. Local setup (test it on your machine first)

```bash
pip install -r requirements.txt
cp .env.example .env          # paste your connection string into .env
python3 seed.py                # creates tables + loads your known accounts/recurring items
streamlit run app.py           # opens at http://localhost:8501
```

## 3. Deploy so you can reach it from your iPhone anywhere

1. Push this folder to a **private** GitHub repo (private, since your
   category rules / recurring items live in code you might commit —
   though actual transaction data stays in the database, not in git).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, click **New app**, point it at your repo, main file `app.py`.
3. Before it deploys: **Advanced settings → Secrets**, paste:
   ```toml
   DATABASE_URL = "postgresql://postgres.xxxxxxxx:[YOUR-PASSWORD]@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"
   ```
4. Deploy. You get a permanent URL — open it in Safari on your iPhone,
   and optionally **Share → Add to Home Screen** so it behaves like an app icon.

Because the database is hosted (not a local file), your local runs and the
deployed app share the exact same data — update Recurring Items on your
phone, see it reflected next time you run it locally, and vice versa.

## How it works

- **`transactions`** is the raw ledger: date, bank_account, item, amount,
  category. Category starts blank.
- Every time the app loads, `categorize.py` matches new transactions
  against your saved **`category_rules`** (keyword → category). Anything
  it can't match is left uncategorized.
- Uncategorized transactions show a warning in the sidebar and queue up
  on the **Categorize** page. When you assign a category there, it's
  saved to that transaction *and* becomes a new rule — so the same kind
  of item is automatic from then on.
- **Recurring Items** and **Extraordinary Items** are the two inputs
  that drive the forecast — edit them directly in their own pages
  (they're editable tables, add/remove rows freely).
- **Accounts** holds your latest known balance per account — this is
  "Live Cash" until a real bank feed is wired in. Update it manually for
  now.
- The **Dashboard** shows: live cash, the 5-month rolling forecast
  (BoP → recurring → extraordinary → EoP, chained month to month), and
  an "Actual vs. Expected" bridge for the current month.
- **Double-counting guard:** if a recurring or extraordinary item already
  has a matching actual transaction in a given month, it's excluded from
  that month's forecast (it's already reflected in the live cash balance)
  — the Dashboard shows exactly which items were excluded and why.

## Bringing in real transaction data

Download a transactions export (CSV) from each bank's online banking site
and save it into `statements_incoming/`. On the **Import Statements** page:

1. The app previews the file's columns.
2. First time for a given account, you map columns once (which column is
   the date, the description, and whether amounts are one signed column or
   separate debit/credit columns). This mapping is saved per account.
3. Every subsequent file from that account applies the saved mapping
   automatically — just drop the file in and import.
4. Already-imported rows are detected and skipped (matched on date + item +
   amount), so re-dropping a statement that overlaps a previous one won't
   create duplicates.
5. Imported files move to `statements_archive/` automatically.

No bank API, no third party, no OAuth — purely files you download yourself.
Categorization runs automatically right after import, same as any other
new transaction.

If your bank only offers PDF statements (not CSV), this importer won't
handle those yet — CSV is far more reliable to parse. Worth checking your
bank's export options for a CSV/Excel format before resorting to PDF.

## Files

| File | Purpose |
|---|---|
| `db.py` | Postgres schema + data access |
| `categorize.py` | Rule-matching engine |
| `forecast.py` | Live cash, 5-month forecast, actual-vs-expected bridge, double-counting guard |
| `import_statements.py` | Reads bank CSV exports from `statements_incoming/`, per-account column mapping, dedup, archiving |
| `app.py` | Streamlit UI (all pages) |
| `seed.py` | One-time setup with your known accounts/recurring items |
| `.env.example` | Template for local DB connection — copy to `.env` |
| `.streamlit/secrets.toml.example` | Template for Streamlit Cloud secrets |
| `statements_incoming/` | Drop bank CSV exports here |
| `statements_archive/` | Imported files land here automatically |

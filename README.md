# Hive — API (backend)

The backend for **Hive** — a Telegram bot + web app that runs a shared flat (house rules,
fines, a common "pot," four recurring bills, dues, a guest experience, and NFC stickers).
A FastAPI app that serves a JSON API at `/api/*`, the **Telegram bot** (aiogram 3, webhook
mode), and the pending-fine sweep — all over one SQLite ledger.

> **The bot is the ledger, the wallet is the jar — they only touch read-only.**
> The app records and calculates; it never holds or moves money.

The **web frontend is a separate repo** → [vijayfagaria-dev/hive-web](https://github.com/vijayfagaria-dev/hive-web).

## Stack

FastAPI · aiogram 3 · SQLite (`aiosqlite`) · bcrypt + signed-cookie sessions · Pydantic.

## Run

```bash
py -3 -m venv .venv && . .venv/Scripts/activate      # Windows
pip install -r requirements.txt
cp .env.example .env          # bot token + WEBHOOK_SECRET + SECRET_KEY (see comments)
uvicorn app.main:app --reload                         # API on :8000
```

Boots **without** a bot token — the API + fine-sweep run; only Telegram stays inert until
you add a token. With no DB it self-creates `hive.db` and seeds a starter rule set.
A new visitor registers as a **guest**; promote a real flatmate to **tenant** via the CLI:

```bash
.venv/Scripts/python.exe -m app.admin list
.venv/Scripts/python.exe -m app.admin promote <username>   # guest -> tenant
```

Set a random `SECRET_KEY` (or `WEBHOOK_SECRET`) before exposing logins — sessions are
signed with it. Optional `FLAT_ADDRESS`/`FLAT_LAT`/`FLAT_LNG`/`FLAT_PLACE_NAME` power the
"Getting here" card; `WALLET_UPI_QR_URL` the pay screen.

## Tests (no pytest needed)

```bash
.venv/Scripts/python.exe tests/smoke_fines.py     # fine lifecycle
.venv/Scripts/python.exe tests/smoke_bot.py        # bot flows (offline dispatcher)
.venv/Scripts/python.exe tests/smoke_auth.py       # bcrypt + accounts/migration
.venv/Scripts/python.exe tests/smoke_location.py   # "Getting here" link builder
.venv/Scripts/python.exe tests/smoke_api.py        # the JSON API (auth, gating, mutations)
HIVE_TEST_MODE=web .venv/Scripts/python.exe tests/smoke_web.py   # health + webhook
```

## Layout

```
.
├── app/
│   ├── main.py        FastAPI app: webhook + /api router + health + fine-sweep
│   ├── api.py         the JSON API (/api/*) consumed by the frontend
│   ├── bot/           aiogram 3 handlers
│   ├── fines.py       the fine lifecycle (the only home for the status workflow)
│   ├── queries.py     all SQLite reads/writes + the money calcs
│   ├── auth.py        bcrypt + session helpers
│   ├── schema.sql     the database schema
│   └── …
├── tests/             smoke suites (run them directly with python)
├── plans/             build plans + adversarial-review logs (v1, v2)
└── requirements.txt
```

The whole product design is in **[DESIGN.md](./DESIGN.md)** (the single source of truth);
build plans + review logs are in [`plans/`](./plans).

# CLAUDE.md — Hive API (backend)

Guidance for Claude Code working in the **hive-api** repo.

## What this is

The **backend** for **Hive** — a *personal hobby project*: a small FastAPI/SQLite app
that runs a shared 4–6 person flat (house rules, complaints/fines, a common "fine pot,"
four recurring bills, dues, a guest experience, and NFC stickers). Web-first as of v4
(the Telegram bot was retired). **Completely independent from any work/corporate
project** — do not import its conventions, memory, or code.

The **web frontend is a separate repo** → [vijayfagaria-dev/hive-web](https://github.com/vijayfagaria-dev/hive-web).
It consumes this app's JSON API (`/api/*`).

**Read `DESIGN.md` first.** It is the single source of truth for the whole product design.

## Guiding principles

- **The bot is the ledger, the wallet is the jar — they only touch read-only.**
  The app records and calculates; it never holds or moves money. Never add code that
  takes custody of funds (that's RBI-licensed territory).
- **Keep it lightweight.** A toy for friends, not a startup. Prefer the simplest thing that
  works; follow the v1→v3 build order in DESIGN.md.
- **Social-first, software-assists.** For dispute/abuse handling, the lightest mechanism +
  visible social stats beat heavy automation.

## Stack

Python 3.11+, **FastAPI**, **SQLAlchemy 2.0 async ORM** + **Alembic**, **SQLite** via
`sqlite+aiosqlite`, bcrypt + signed-cookie sessions. One app serves the **JSON API**
(`/api/*`) and `/health` (+ the complaint sweep). Hosting: Oracle Cloud Always Free VM.

## Architecture (layered — keep the boundaries)

```
app/
  api/        thin routers (request/response only) + deps (session, auth)
  schemas/    Pydantic request bodies + response mappers (the wire contract)
  services/   business logic (complaints, billing, accounts, reporting, notifications)
  repositories/  ORM queries only — NO commits (the session owns the transaction)
  db/         SQLAlchemy models, async session/engine, seed
  domain/     enums, time, static content (nfc) — pure, transport-free
  core/       config, logging, errors (+ handlers), security  (cross-cutting)
  infra/      storage (proof files)
  alembic/    migrations (schema source of truth)
```

Rules: **routes → services → repositories → models**. Routes never touch the ORM
or business rules; repositories never commit (a request = one unit of work via
`get_session`; the sweep/CLI use `session_scope`). Services raise `core.errors`
exceptions; the central handler maps them to HTTP. Add a feature = add a model +
repo + service + schema + route; nothing else changes.

> **v4 update — web-first; Telegram bot retired.** Telegram use in India is low, so
> the aiogram bot (input *and* push) was removed; the product is the **Next.js web
> app** over this JSON API. Complaints require **image proof** and run an
> accept / deny→vote workflow (`app/fines.py`). Notifications are **in-app + Web Push
> (VAPID) + email + WhatsApp (Meta Cloud API, template msgs)** (`app/notify.py`) —
> channel-pluggable; each is best-effort and skipped when unconfigured. No more aiogram/webhook.

## Conventions

- One app, one SQLite file. **Models** in `app/db/models/` are the schema; keep
  `DESIGN.md` and Alembic migrations in sync with them.
- `bill_shares` must be a **point-in-time snapshot** (one row per active tenant at
  bill-creation) — never compute splits live. Load-bearing; lives in `services/billing.py`.
- Complaints/fines are claims, not verdicts: respect the `status` workflow
  (pending→confirmed/disputed/void/upheld). All transitions live in `services/complaints.py`.
- ORM usage: repositories hold the queries and **never commit**; transitions mutate
  loaded entities and the session flushes/commits. No raw SQL unless truly necessary.
- Schema changes: edit the model, then `alembic revision --autogenerate -m "..."`,
  review, commit. Fresh DBs self-provision via `create_all` at startup.
- Secrets (`SECRET_KEY`, VAPID keys, SMTP creds, etc.) via a `.env` file (gitignored) — never commit them.

## Commands

```bash
uvicorn app.main:app --reload                       # JSON API on :8000 (self-provisions a fresh DB)
.venv/bin/python3 -m alembic upgrade head           # apply migrations (prod / existing DB)
.venv/bin/python3 -m alembic revision --autogenerate -m "msg"   # after a model change
.venv/bin/python3 tests/smoke_fines.py              # run any smoke suite directly (macOS/Linux venv)
python -m app.admin promote <username>              # guest -> tenant (only path to tenant)
```

## Build order

See `DESIGN.md` → "Build order". Ship v1 (tenants + fines + bills + dues, with
`bill_shares` snapshots and the Layer-1 cooling window) before anything else.

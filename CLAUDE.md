# CLAUDE.md — Hive API (backend)

Guidance for Claude Code working in the **hive-api** repo.

## What this is

The **backend** for **Hive** — a *personal hobby project*: a Telegram bot + small
FastAPI/SQLite app that runs a shared 4–6 person flat (house rules, fines, a common "fine
pot," four recurring bills, dues, a guest experience, and NFC stickers). **Completely
independent from any work/corporate project** — do not import its conventions, memory, or code.

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

Python 3.11+, **FastAPI** (webhook mode for the bot), **aiogram 3**, **SQLite** via
`aiosqlite`, bcrypt + signed-cookie sessions. One app serves the Telegram webhook, the
**JSON API** (`/api/*`), and `/health` (+ the fine-sweep). Hosting: Oracle Cloud Always
Free VM (api + DB on one box).

## Conventions

- One app, one SQLite file. Schema lives in `DESIGN.md` → keep code and that doc in sync.
- `bill_shares` must be a **point-in-time snapshot** (one row per active tenant at
  bill-creation) — never compute splits live. This is load-bearing; don't "simplify" it.
- Fines are claims, not verdicts: respect the `status` workflow
  (pending→confirmed/disputed/void/upheld). See DESIGN.md "Handling fine-system abuse."
- Secrets (bot token, etc.) via a `.env` file (gitignored) — never commit them.

## Commands

```bash
uvicorn app.main:app --reload                       # API + bot on :8000
.venv/Scripts/python.exe tests/smoke_fines.py       # run any smoke suite directly
```

## Build order

See `DESIGN.md` → "Build order". Ship v1 (tenants + fines + bills + dues, with
`bill_shares` snapshots and the Layer-1 cooling window) before anything else.

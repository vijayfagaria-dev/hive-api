# Hive — API (backend)

The backend for **Hive** — a small web app that runs a shared 4–6 person flat: house
rules, photo-proof **complaints** (accept / deny → flat **vote** → a shared fine "pot"),
four recurring **bills**, **dues**, a guest experience, NFC spot pages, and notifications.
A **FastAPI** app serving a JSON API at `/api/*` plus a background sweep that
auto-confirms overdue complaints and finalizes closed votes — over one SQLite database.

> **The app is the ledger, the wallet is the jar — they only touch read-only.**
> It records and calculates; it never holds or moves money.

Web-first since v4 (the Telegram bot was retired). The **web frontend is a separate repo**
→ [vijayfagaria-dev/hive-web](https://github.com/vijayfagaria-dev/hive-web); it consumes
this JSON API and the dev server proxies `/api` here so auth stays same-origin.

## Stack

FastAPI · **SQLAlchemy 2.0 async ORM** + **Alembic** · SQLite (`sqlite+aiosqlite`) ·
bcrypt + signed-cookie sessions · Pydantic. Notifications fan out to in-app + Web Push
(VAPID) + email + WhatsApp (Cloud API).

## Architecture (layered)

```
app/
  api/        thin routers (request/response only) + deps (session, auth)
  schemas/    Pydantic request bodies + response mappers (the wire contract)
  services/   business logic (complaints, billing, accounts, reporting, notifications)
  repositories/  ORM queries only — never commit (the session owns the transaction)
  db/         SQLAlchemy models, async engine/session, seed
  domain/     enums, time, static content (nfc) — pure, transport-free
  core/       config, logging, errors (+ handlers), security
  infra/      proof-image storage
alembic/      migrations (schema source of truth)
tests/        standalone smoke suites (no pytest)
```

Flow: **routes → services → repositories → models**. Adding a feature = add a model + repo
+ service + schema + route. See [DESIGN.md](./DESIGN.md) (product) and [CLAUDE.md](./CLAUDE.md)
(house rules); the frontend contract is in [FRONTEND_BRIEF.md](./FRONTEND_BRIEF.md).

## Run

```bash
python3 -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # set SECRET_KEY (+ optional VAPID/SMTP/WhatsApp)
uvicorn app.main:app --reload                         # JSON API on :8000
```

A fresh DB self-provisions (`create_all` + a starter rule set) on first boot. New visitors
register as a **guest**; promote a real flatmate to **tenant** via the CLI:

```bash
python -m app.admin list
python -m app.admin promote <username>                # guest -> tenant
```

Set a random `SECRET_KEY` before exposing logins (sessions are signed with it). Optional:
`VAPID_*` (Web Push), `SMTP_*` (email), `WHATSAPP_*` (WhatsApp Cloud API),
`FLAT_*` ("Getting here" card), `WALLET_UPI_QR_URL` (pay screen) — see `.env.example`.

## Migrations (Alembic)

`create_all` provisions fresh/dev DBs; **Alembic is the source of truth for evolving an
existing DB.**

```bash
alembic upgrade head                                  # apply migrations
alembic revision --autogenerate -m "describe change"  # after editing a model
```

## Tests (no pytest needed)

Standalone smoke suites against throwaway temp DBs — exit non-zero on first failure:

```bash
.venv/bin/python3 tests/smoke_fines.py      # complaint lifecycle (service + ORM)
.venv/bin/python3 tests/smoke_auth.py       # bcrypt + accounts + unique-username index
.venv/bin/python3 tests/smoke_api.py        # the JSON API (auth, role gating, mutations)
.venv/bin/python3 tests/smoke_location.py   # "Getting here" link builder
.venv/bin/python3 tests/smoke_web.py        # health + that the bot/webhook is retired
```

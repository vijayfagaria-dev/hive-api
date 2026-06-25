# Hive — v1 (MVP) — Overview

> **Plan folder:** `plans/v1/`
> **Status:** DRAFT — plan-driven build of the DESIGN.md v1 scope
> **Generated:** 2026-06-22
> **Related files:** [requirements](requirements.md) | [data-dictionary](data-dictionary.md) | [business-rules](business-rules.md) | [api-surface](api-surface.md) | [shared-definitions](shared-definitions.md) | [task-summary](task-summary.md)

---

## Executive Summary

**What this delivers:**
The v1 (MVP) slice of Hive — a Telegram bot + small FastAPI/SQLite app that runs a shared flat for 4–6 tenants. v1 covers: tenants (no guests yet), the rules list with favorites/categories/search, one-tap `/fine` into a shared fine pot, the four recurring bills split with **point-in-time `bill_shares` snapshots**, dues tracking, and the `/pot` / `/dues` quick checks. The fine workflow ships **Layer 1 only** (a cooling window + lazy consensus) plus a **visible overturn stat**.

**Why it matters:**
This is the smallest thing that is actually useful day-to-day: log a fine in one tap, see the pot, see who owes what. Everything heavier (guests, NFC, dispute voting, loser-pays, auto money-ingest) is deliberately deferred so we ship something we'll actually use before gold-plating.

**The one principle that drives every decision:**
> The bot is the *ledger*, the wallet is the *jar*, and the two only ever touch read-only. The app records and calculates; it never holds or moves money.

**Scope:**
One FastAPI app process serving the Telegram webhook + a read-only HTML dashboard, backed by one SQLite file.
  New SQL tables: 6 (`members`, `rules`, `fines`, `fine_votes`, `bills`, `bill_shares`) | New endpoints: 3 web routes + the bot surface | Background jobs: 1 (pending-fine sweep)
  Total tasks: 14 across 5 phases.

**Effort estimate:** S–M — small surface, but the fine lifecycle and the bill snapshot carry the real correctness weight.

**Risk level:** Low (hobby project, ~6 users, no money custody). The two load-bearing bits are the `bill_shares` snapshot and the fine `status` workflow; both are pinned by business rules + the schema.

**Dependencies:** A Telegram bot token from @BotFather for the live bot. None of the web/DB work is blocked on it — the app boots and the dashboard renders with the bot disabled (empty token).

---

## Build-order Coverage Matrix

DESIGN.md → "Build order" → v1. Each v1 deliverable maps to a phase.

| # | v1 deliverable (DESIGN.md) | Status | Phase |
|---|---|---|---|
| 1 | Tenants only (members, roles, lifecycle) | Covered | P1, P3 |
| 2 | Rules + favorites / categories / search | Covered | P1, P3, P5 |
| 3 | `/fine` → pot, Layer-1 cooling window | Covered | P2, P3 |
| 4 | Bill split with `bill_shares` snapshots **from day one** | Covered | P1, P3 |
| 5 | Dues (unpaid confirmed fines + unpaid bill shares) | Covered | P1, P3, P5 |
| 6 | `/pot` `/dues` quick checks | Covered | P3 |
| 7 | Visible overturn stat (accuser accountability, read-only) | Covered | P1, P5 |

Explicitly **deferred** to v2/v3 (not in this plan): guest role + welcome page, NFC `/s/<spot>` routes, dispute voting / `fine_votes` logic, loser-pays, reputation downgrade, month-end auto-settle (applying pot to rent), auto read-only money ingest (SMS/email).

---

## Deployment Strategy & Data Migration

**Deployment:** single process, single SQLite file. `uvicorn app.main:app`. On Oracle Cloud Always Free for the live deploy; `--reload` locally. No migration framework in v1 — `schema.sql` is idempotent (`CREATE TABLE IF NOT EXISTS`) and applied on every boot. If the schema ever changes shape, v1's answer is "delete the dev db and reseed"; a real migration tool is out of scope until the data is worth keeping.

**Data migration:** none. First boot creates the schema and seeds a starter rule set (`seed.py`) only if `rules` is empty.

---

## Technical Feasibility

- **Architecture fit.** One FastAPI app. Two faces, one backend: the Telegram webhook (aiogram 3, fed from a FastAPI route) and a Jinja2 dashboard. Both read/write the same SQLite via a single shared `aiosqlite` connection — never out of sync.
- **Data layer.** Plain SQL in `queries.py`; the connection is passed in explicitly so the same functions serve the bot and the web. Money is stored as **integer rupees**; timestamps as **ISO-8601 UTC TEXT**.
- **The load-bearing snapshot.** `create_bill_with_shares()` writes one `bill_shares` row per active tenant at creation time. Splits are **never** computed live. (See BR-003.)
- **The fine lifecycle.** A pending fine carries a `confirm_deadline`. A background sweep (every ~5 min) promotes overdue, undisputed pendings to `confirmed`. The `status` column is the source of truth for the pot; the sweep keeps it honest.
- **Scale.** ~6 people, ~100 rules, years of data — trivial for SQLite. No pool, no cache, no framework beyond FastAPI + aiogram.
- **Security / money.** The app never holds funds. The webhook path carries an unguessable secret and Telegram's secret-token header is verified.

---

## Phases (see task-summary.md)

1. **Data foundation & ledger** — schema, config, db bootstrap+seed, all queries + money calcs.
2. **Fine lifecycle (Layer 1)** — create / dispute / pay + cooling-window sweep.
3. **Telegram bot** — `/start` `/pot` `/dues` `/fine` `/bill`, rule pickers, Dispute button.
4. **FastAPI wiring** — lifespan, webhook route, dashboard route, health, sweep task.
5. **Dashboard + seed** — Jinja2 pages, CSS, starter rules.

## Out of Scope (v1)

- ❌ The app holding/moving money (the throwaway wallet does custody).
- ❌ Guests, the guest welcome page, NFC `/s/<spot>` routes (v2).
- ❌ Dispute voting, loser-pays, reputation downgrade, month-end settle, auto money-ingest (v3).
- ❌ Splitting arbitrary expenses — only rent, house help, electricity, water.
- ❌ A heavy frontend framework — Jinja2 + the bot are the whole UI.

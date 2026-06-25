# Task Summary — Hive v1 (MVP)

> Human-readable progress tracker. **Phases** group ordered tasks; each task is implemented then reviewed.
> Status legend at the bottom.

**Plan folder:** `plans/v1/`
**Generated:** 2026-06-22
**Phases:** 5 | **Tasks:** 14

---

## Phase 1: Data foundation & ledger

**Goal:** One SQLite file with the full v1 schema (incl. the `bill_shares` snapshot table), config from `.env`, a self-seeding bootstrap, and all data-access + money calcs in one place.

**Tasks: 4**

| Task | Title | Type | Status | Implemented | Reviewed | Notes |
| ---- | ----- | ---- | ------ | ----------- | -------- | ----- |
| 1 | `schema.sql` — 6 tables + indexes, snapshot + forward-compat columns | Schema | ✅ Completed | 2026-06-22 | — | Matches data-dictionary.md; CHECK constraints pin BR-030/040/041. |
| 2 | `config.py` — frozen `Settings` from `.env`, `bot_enabled`/`webhook_*` | Config | ✅ Completed | 2026-06-22 | — | Empty token allowed (BR-060). |
| 3 | `db.py` — `connect()` (schema apply + seed-if-empty), UTC time helpers | Infra | ✅ Completed | 2026-06-22 | — | WAL + FK on; `now_iso`/`deadline_iso`. |
| 4 | `queries.py` — members/rules/fines/bills + `pot_total`/`member_dues`/`overturn_stats` + `create_bill_with_shares` | Repository | ✅ Completed | 2026-06-22 | 2026-06-22 | Snapshot + remainder-to-first (BR-003/042); `OWED_STATUSES`. Phase-2 review trimmed dead `set_fine_status`; `insert_fine` gained a `ts` param. |

---

## Phase 2: Fine lifecycle (Layer 1)

**Goal:** The fine state machine — create as `pending` with a cooling deadline, one-tap dispute, mark paid, and the sweep that auto-confirms overdue undisputed pendings.

**Tasks: 1**

| Task | Title | Type | Status | Implemented | Reviewed | Notes |
| ---- | ----- | ---- | ------ | ----------- | -------- | ----- |
| 5 | `fines.py` — `create_fine` (pending + deadline + bump use_count), `sweep_due` (BR-032), guarded dispute/pay wrappers | Service | ✅ Completed | 2026-06-22 | 2026-06-22 | The status workflow lives here, not in handlers. Smoke-tested (`tests/smoke_fines.py`) + adversarial review gate (24→10 findings, all triaged; see Review log). |

---

## Phase 3: Telegram bot

**Goal:** The tap-driven input surface — `/start`, quick checks, the `/fine` and `/bill` flows, the Dispute button.

**Tasks: 5**

**Files:** split for clarity — `bot/{__init__,setup,callbacks,formatting,keyboards,common,onboarding,checks,fine_flow,bill_flow}.py`. Verified offline via `tests/smoke_bot.py` (15 end-to-end checks through the real dispatcher) + the Phase 3 review gate (23→20 findings; see Review log).

| Task | Title | Type | Status | Implemented | Reviewed | Notes |
| ---- | ----- | ---- | ------ | ----------- | -------- | ----- |
| 6 | `bot/setup.py` — Bot + Dispatcher, member middleware, DI of the db connection, router registration | Bot | ✅ Completed | 2026-06-22 | 2026-06-22 | aiogram 3.29; only built when `bot_enabled`. |
| 7 | `bot/{callbacks,formatting,keyboards}.py` — typed callbacks, text builders, inline keyboards | Bot | ✅ Completed | 2026-06-22 | 2026-06-22 | Stateless flows; never show all rules (BR-020). |
| 8 | `bot/{onboarding,checks}.py` — `/start`+`/addtenant`+claim (BR-010), `/pot`, `/dues`(+`all`), `/rules` | Bot | ✅ Completed | 2026-06-22 | 2026-06-22 | Onboarding model is a documented BR-010 refinement. |
| 9 | `bot/fine_flow.py` — rule → accused → pending; Dispute + pay callbacks | Bot | ✅ Completed | 2026-06-22 | 2026-06-22 | Accused picker excludes reporter (BR-034). |
| 10 | `bot/bill_flow.py` — `/bill <type> <amount> [month]` → snapshot shares; share-pay | Bot | ✅ Completed | 2026-06-22 | 2026-06-22 | Calls `create_bill_with_shares` (BR-003). |

---

## Phase 4: FastAPI wiring

**Goal:** One app process that bootstraps the db, (optionally) registers the Telegram webhook, runs the sweep, and serves health + dashboard.

**Tasks: 2**

| Task | Title | Type | Status | Implemented | Reviewed | Notes |
| ---- | ----- | ---- | ------ | ----------- | -------- | ----- |
| 11 | `main.py` — lifespan (connect db, set webhook if enabled, sweep loop, always-cleanup), webhook route (secret-guarded + always-200, BR-061), `/health` | App | ✅ Completed | 2026-06-22 | 2026-06-22 | Replaces the placeholder. Boots web-only with no token (BR-060). |
| 12 | Dashboard route `GET /` — render pot + dues + recent fines + overturn stat | App | ✅ Completed | 2026-06-22 | 2026-06-22 | Read-only (OQ-2); Jinja2 autoescape on. |

---

## Phase 5: Dashboard + seed

**Goal:** The read-only overview page and a starter rule set so the bot has buttons on first boot.

**Tasks: 2**

| Task | Title | Type | Status | Implemented | Reviewed | Notes |
| ---- | ----- | ---- | ------ | ----------- | -------- | ----- |
| 13 | `templates/` (base + dashboard) + `static/style.css` | Web | ✅ Completed | 2026-06-22 | 2026-06-22 | **Built alongside the Phase 4 dashboard route (task 12)** — the route can't render without it. Pot, dues table, recent fines, Hall-of-Shame board; exercised by `tests/smoke_web.py`. |
| 14 | `seed.py` — starter rules across categories, clearly marked placeholder | Data | ✅ Completed | 2026-06-22 | — | **Pulled forward into Phase 2:** `db.py`'s bootstrap hard-depends on it, so the app couldn't boot without it. 16 rules / 8 categories. Real list pasted later. |

---

## Legend
- ⏳ **Pending** — not yet started
- 🟡 **In progress**
- ✅ **Completed** — implemented (and reviewed where noted)
- ⚠️ **Pending verification** — implemented but a runtime check still required
- ❌ **Fix required** — review flagged issues

## Notes
- Phase 1 was implemented up-front (before the plan docs were written) directly from DESIGN.md, then back-filled into this plan. The Phase 2 review also covered the Phase 1 data layer it depends on (`queries.py`, `db.py`), so those are now marked reviewed.
- Build strictly in phase order; don't gold-plate. v2 (guests, NFC) and v3 (voting, money-ingest, settle) are separate plans.
- A standalone regression check lives at `tests/smoke_fines.py` (no pytest needed): `.venv/Scripts/python.exe tests/smoke_fines.py`. Not a formal suite — a lightweight guard for the load-bearing fine lifecycle.

## Review log

### Phase 2 — `fines.py` (2026-06-22)
Adversarial multi-lens review (5 lenses → per-finding verify): **24 raw → 10 confirmed**. Applied:
- **[fix-now]** `mark_paid` now rejects non-`OWED_STATUSES` fines (a pending fine marked paid would later sweep into the pot yet vanish from dues — ledger desync). Also returns a bool (idempotent on Telegram's duplicate callback delivery). → BR-036.
- `sweep_due` collapsed to one atomic `UPDATE … RETURNING id` — returns exactly the rows promoted (the old SELECT-then-UPDATE could report an id disputed in the gap) and drops a query. → BR-032.
- Deleted dead, unguarded `queries.set_fine_status` (a status-transition escape hatch around the service). → BR-030.
- `create_fine` derives `ts` + `confirm_deadline` from one clock read, so `confirm_deadline == ts + COOLING_HOURS` exactly. → BR-031.
- `create_fine` rejects an inactive accused/accuser. → BR-001.
- **[wont-fix]** use_count bump being a second commit (non-atomic with the insert) — irrelevant for a self-tuning heuristic on a single-connection toy; adding a transaction wrapper would be over-engineering.

### Phase 3 — the bot (2026-06-22)
Adversarial 6-lens review (per-finding verify): **23 raw → 20 confirmed**, deduping to 9 distinct fixes — all applied:
- **[fix-now]** `/dues` bill-share button emitted `BillShare` (the bill-card handler), clobbering the caller's private dues into the shared bill card *and* exposing other tenants' share buttons; `DuesShare`/`cb_dues_share` were dead code. Re-wired `dues_kb` to `DuesShare` (marks only the caller's share, re-renders dues).
- **[fix-now]** Callback edits called `callback.message.edit_text` directly → crash on a stale (None / `InaccessibleMessage`) tap, and an uncaught "not modified" on double-taps. Hardened `safe_edit` (guards both) and routed every callback edit through it.
- Paying the **last** bill share left an empty inline keyboard (Telegram rejects it) → now drops the keyboard.
- `/addtenant` duplicate-name guard; founder bootstrap now keys off "ever had a member" (not active-only); dispute double-tap says "Already disputed" vs "already confirmed"; `/bill` month regex rejects `2026-13`/`2026-00`; wired `/dues all` (whole-flat table — makes `all_dues()` live).
- **[doc]** Back-filled `api-surface.md` (onboarding model, `/addtenant`, `/dues all`, real callback prefixes, `DuesShare`/`BillShare` split; removed the nonexistent `bill:type` picker).
- Regression coverage added to `tests/smoke_bot.py` (DuesShare routing, last-share keyboard clear, `/dues all`, no-message safe_edit) — **15/15 green**.

### Phase 4 — FastAPI wiring + dashboard (2026-06-22)
Adversarial 5-lens review (per-finding verify): **17 raw → 16 confirmed**, deduping to 5 distinct fixes — all applied:
- **[fix-now]** The webhook ran `Update.model_validate` + `feed_update` unguarded → a handler raise or malformed body became a **500**, which Telegram retries → re-running side effects (a duplicate fine inflates the pot, breaking BR-035). Now wrapped: log + always ACK **200**. (Verifier confirmed `feed_webhook_update` is *not* a reliable substitute.)
- **[fix-now]** `webhook_secret` defaulted to the repo-visible `hive-dev-secret` and was absent from `.env.example` → a copied `.env` shipped the known default, defeating BR-061. Added `WEBHOOK_SECRET` (+ charset note + optional `COOLING_HOURS`/`SWEEP_INTERVAL_SECONDS`) to `.env.example`; lifespan now logs a loud warning if a public webhook is registered with the default secret.
- Lifespan restructured so the DB connection + bot session + sweep task are **always** released even if startup raises; `set_webhook` is now non-fatal (dashboard still serves if Telegram is down).
- Overturn board empty-state ("No reports filed yet") was unreachable (LEFT JOIN always returns rows) → the route now hides the board until someone has actually filed.
- **[doc]** `.env.example`, `task-summary.md` (this), and `README.md` brought in sync; `api-surface.md` §1 web routes already matched.
- Regression added to `tests/smoke_web.py` (malformed-body → 200). All four suites green: `smoke_fines`, `smoke_bot`, `smoke_web[web]`, `smoke_web[bot]`.

**v1 (MVP) is now feature-complete** — tenants · rules · fines (Layer-1 cooling window) · bills (point-in-time `bill_shares` snapshots) · dues · `/pot`/`/dues` · visible overturn stat · read-only dashboard. Live run needs only a @BotFather token + a public `WEBHOOK_BASE_URL`.

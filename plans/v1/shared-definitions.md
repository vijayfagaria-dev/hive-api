# Hive — v1 — Shared Definitions

> **Plan folder:** `plans/v1/`
> **Status:** DRAFT
> **Related files:** [overview](overview.md) | [requirements](requirements.md) | [data-dictionary](data-dictionary.md) | [business-rules](business-rules.md) | [api-surface](api-surface.md) | [task-summary](task-summary.md)

The shared vocabulary. Any term used in the other v1 docs is defined here once.

## Domain terms

| Term | Definition |
|---|---|
| **Tenant** | A full, permanent member of the flat. In bill splits, can fine anyone, pay, manage rules. `members.role = 'tenant'`. v1 has tenants only. |
| **Guest** | A lightweight, temporary member (subject to fines, not in bill splits). `members.role = 'guest'`, `host_id` set. Schema exists in v1; behaviour is v2. |
| **The pot** | The shared fine jar's running total = `SUM(fines.amount)` where `status IN ('confirmed','upheld')`. The app *tracks* this; the physical money lives in the throwaway wallet. |
| **Dues** | What a member owes right now = unpaid `confirmed`/`upheld` fines + unpaid `bill_shares`. |
| **Fine** | A *claim* that someone broke a rule. Not a verdict until its `status` resolves. Carries the accused (`member_id`), the accuser (`added_by`), an `amount`, and a `status`. |
| **Cooling window** | The grace period (`COOLING_HOURS`, default 12h) between a fine being reported and auto-confirming. Anyone can tap **Dispute** within it. Implements DESIGN Layer 1 (lazy consensus). |
| **Sweep** | The background job that promotes `pending` fines whose `confirm_deadline` has passed (and aren't disputed) to `confirmed`. Keeps `status` truthful so the pot is correct. |
| **Snapshot (`bill_shares`)** | A point-in-time freeze: at bill creation, one row per active tenant with that month's `share_amount`. Load-bearing — never recompute splits live. |
| **Overturn stat** | Per-member accuser-accountability numbers: fines **filed** (`added_by`), still **upheld**, and **overturned** (`void`/`disputed`), plus an overturn %. Visible; the v1 anti-abuse lever. |

## Fine status workflow

```
            ┌──────────── Dispute (one tap, anyone) ──────────► disputed ──(humans, monthly)─► upheld | void
 pending ───┤
            └──── cooling window elapses, undisputed (sweep) ─► confirmed
```

| Status | Meaning | Counts toward pot/dues? | Set by (v1) |
|---|---|---|---|
| `pending` | Reported, inside the cooling window | No | fine create |
| `confirmed` | Cooling window elapsed undisputed | **Yes** | sweep |
| `disputed` | Someone tapped Dispute; parked for humans | No | Dispute button |
| `void` | Thrown out | No | (v3 voting; manual only in v1) |
| `upheld` | Contested but stood | **Yes** | (v3 voting; manual only in v1) |

`OWED_STATUSES = ('confirmed', 'upheld')` — the single definition of "counts as real money."

## Representation conventions

| Thing | Representation | Rationale |
|---|---|---|
| Money | **Integer rupees** (`INTEGER`) | The pot is small; paise are noise. No floats for money. |
| Timestamps & deadlines | **ISO-8601 UTC TEXT**, e.g. `2026-06-22T11:30:00Z` | Sorts lexically in SQLite; renders directly. Helpers in `db.py` (`now_iso`, `deadline_iso`). |
| Month (for bills) | `'YYYY-MM'` TEXT | Human + sortable. |
| Booleans | `INTEGER` 0/1 | SQLite has no bool. |

## Code-level shared symbols

| Symbol | Location | Purpose |
|---|---|---|
| `settings` | `app/config.py` | Frozen `Settings` dataclass from `.env`. `bot_enabled`, `webhook_path`, `webhook_url`, `cooling_hours`. |
| `connect()` | `app/db.py` | Opens the shared connection, applies schema, seeds if empty. |
| `now_iso()` / `deadline_iso(h)` | `app/db.py` | UTC ISO timestamp / cooling deadline. |
| `OWED_STATUSES` | `app/queries.py` | `('confirmed','upheld')` — the owed-money status set. |
| `queries.*` | `app/queries.py` | All data-access + money calcs; every function takes the connection explicitly. |

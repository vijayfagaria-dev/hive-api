# Hive — v1 — Requirements

> **Plan folder:** `plans/v1/`
> **Status:** DRAFT — distilled from DESIGN.md (the single source of truth)
> **Related files:** [overview](overview.md) | [data-dictionary](data-dictionary.md) | [business-rules](business-rules.md) | [api-surface](api-surface.md) | [shared-definitions](shared-definitions.md) | [task-summary](task-summary.md)

Requirements are tagged `[Explicit]` (stated in DESIGN.md) or `[Inferred]` (a reasonable
filling-in of a gap, flagged as an open question if it could go either way). Each maps to a
business rule (`business-rules.md`) and/or surface (`api-surface.md`).

## Members & roles

- **REQ-M-001** `[Explicit]` v1 has **tenants only**. A tenant is a full member: in bill splits, can fine anyone, can pay, can manage rules. → BR-001
- **REQ-M-002** `[Explicit]` The `guest` role and `host_id` exist in the schema from v1 but no guest *behaviour* ships until v2. The columns must not be retrofitted later. → BR-002
- **REQ-M-003** `[Explicit]` Permissions are flat — every active tenant can do everything. No admin role in v1.
- **REQ-M-004** `[Inferred]` A member is created with a name; their `telegram_id` is linked when they first `/start` the bot. → BR-010

## Rules

- **REQ-R-001** `[Explicit]` Store up to ~100 rules; the challenge is *selecting* one fast, never showing 100 buttons.
- **REQ-R-002** `[Explicit]` Selection works four ways: favorites first (~10 ⭐), browse by category, search/type-ahead, fuzzy text. v1 ships favorites + category browse + text search. → BR-020
- **REQ-R-003** `[Explicit]` `use_count` self-tunes — most-fined rules bubble up within their list. → BR-021
- **REQ-R-004** `[Inferred]` Managing the full rule list is a dashboard/table job, not a chat job; v1 seeds a starter set and reads it everywhere. Editing rules in-app is deferred.

## Fines (the pot)

- **REQ-F-001** `[Explicit]` A fine is a **claim, not a verdict**. It moves through `pending → confirmed | disputed | void | upheld`. → BR-030
- **REQ-F-002** `[Explicit]` v1 ships **Layer 1 only**: a pending fine **auto-confirms after a cooling window** (~12h) *unless* someone taps **Dispute**. → BR-031, BR-032
- **REQ-F-003** `[Explicit]` Disputing must stay **one tap** — contesting must never be more expensive than paying. In v1 a disputed fine simply parks for the humans (monthly meeting); no auto-resolution. → BR-033
- **REQ-F-004** `[Explicit]` Every fine records `added_by` (the accuser) for accountability. → BR-034
- **REQ-F-005** `[Explicit]` The **pot** = `sum(amount)` of fines with status `confirmed`/`upheld`. (Applying the pot to rent at month-end is v3; until then nothing is applied.) → BR-035
- **REQ-F-006** `[Explicit]` A fine can be marked **paid** independently of its status; `paid` is separate from `status`. → BR-036
- **REQ-F-007** `[Inferred]` v1 keeps rate-limits/severity-tiers minimal: the cooling window applies uniformly; `severity_tier` and `auto_confirm` exist on `rules` for v3 tuning but don't branch behaviour yet. **OQ-1.**

## Bills

- **REQ-B-001** `[Explicit]` Only four bill types: `rent`, `house_help`, `electricity`, `water`. No arbitrary expenses. → BR-040
- **REQ-B-002** `[Explicit]` **Splits are point-in-time.** On bill creation, snapshot one `bill_shares` row per **currently-active tenant**. Never compute `total ÷ count` live. June stays ÷4 forever even after July splits ÷6. → BR-003
- **REQ-B-003** `[Explicit]` Guests do **not** pay bills — only active tenants are in a split. → BR-041
- **REQ-B-004** `[Inferred]` Integer-rupee splits must sum to exactly `total`; the remainder goes to one tenant rather than being lost to rounding. → BR-042
- **REQ-B-005** `[Inferred]` A share is marked paid per `(bill, member)`. → BR-043

## Dues & checks

- **REQ-D-001** `[Explicit]` A member's **dues** = unpaid `confirmed`/`upheld` fines + unpaid `bill_shares`. → BR-050
- **REQ-D-002** `[Explicit]` `/pot` and `/dues` are one-tap quick checks in the bot. → api-surface
- **REQ-D-003** `[Explicit]` The **overturn stat** (reports filed / upheld / overturned per member) is **visible** — it's the v1 anti-abuse mechanism (social pressure beats algorithms). Read-only in v1. → BR-051

## Platform

- **REQ-P-001** `[Explicit]` Python 3.11+, FastAPI (webhook mode), aiogram 3, SQLite via aiosqlite, Jinja2. One app, one SQLite file.
- **REQ-P-002** `[Explicit]` Secrets via `.env` (gitignored) — never committed.
- **REQ-P-003** `[Inferred]` The app must boot and serve the dashboard/health with **no bot token** set, so the web side is usable before @BotFather setup. → BR-060
- **REQ-P-004** `[Inferred]` The Telegram webhook must reject requests that don't carry the configured secret. → BR-061

## Open questions

- **OQ-1** Should v1 already branch on `severity_tier` (e.g. >₹50 needs a co-sign) or keep the cooling window uniform? **Plan assumption: uniform** (DESIGN says ship Layer 1 first, add the rest only if gamed). Revisit in v3.
- **OQ-2** Dashboard as a Telegram Mini App vs a standalone page (DESIGN open decision). **Plan assumption: a plain read-only HTML dashboard** for v1 (no auth, no Mini App SDK). Identity/management UI is a later call.
- **OQ-3** How are bills created in v1 — bot command or dashboard? **Plan assumption: a `/bill` bot command** creates the bill + snapshot; richer management is dashboard/v3.

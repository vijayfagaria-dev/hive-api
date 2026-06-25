# Hive — v2 — Overview

> **Plan folder:** `plans/v2/`
> **Status:** DRAFT — revised to the simple-accounts model. Awaiting review before Phase 1 code.
> **Generated:** 2026-06-24
> **Builds on:** v1 (feature-complete). Related: [requirements](requirements.md) · [data-dictionary](data-dictionary.md) · [business-rules](business-rules.md) · [api-surface](api-surface.md) · [shared-definitions](shared-definitions.md) · [task-summary](task-summary.md)

---

## Executive Summary

**What this delivers:**
The v2 slice of Hive — **simple web accounts**, the **guest experience** (incl. *getting to the flat*), and **NFC stickers**. Anyone can self-register with a username + password and starts as a **guest**; a tenant manually promotes the real flatmates to **tenant**. Guests get a friendly web page to find their way to the flat, view the rules, report, and pay; tenants get the v1 dashboard + management. NFC `/s/<spot>` stickers open the right page per spot.

**The role does real work in exactly two places** (see [business-rules](business-rules.md)):
1. **Bills** — only tenants are in `bill_shares`; a guest never owes rent.
2. **Access** — tenants get the dashboard + management; guests only view rules / report / pay.
Everything else (being fined, reporting, paying, the pot/dues math) is identical. The role is just the existing `members.role` TEXT column — **no roles table, no roleId**.

**New "very important" feature — Getting here.** When a tenant shares the guest link, the guest's page solves the *how do I get there* problem: see the flat **on a map** (opens in whatever map app they have), **copy the address** (cab-app-ready), and **book a ride** via Uber/Ola deep links (Rapido → copy-address fallback).

**The principle is unchanged:**
> The bot is the ledger, the wallet is the jar — they only touch read-only. v2 still **never moves money**; "pay" shows the wallet QR and records a claim.

**Scope (additive on v1):**
  New SQL tables: 0 · New `members` columns: 2 (`username`, `password_hash`) · New config (env): flat address + coordinates, plus the existing wallet QR · New web routes: register/login/logout, guest pages, `/s/<spot>` · NFC spots: code config.

**Effort:** M. **Risk:** low–medium — new public pages + password storage (kept minimal: stdlib hashing, signed-cookie session).

**Dependencies (deploy-time config, none block building/testing):** the **flat's address + lat/lng** (for Getting here), the **wallet UPI QR** (`WALLET_UPI_QR_URL`, for pay), ~₹300 of **NTAG213 stickers** (to deploy NFC; routes work from any browser without them).

---

## Build-order Coverage

DESIGN.md → "Build order" → v2 = guest role + welcome page + self-pay + NFC. **Getting here** is an *added* v2 requirement (the user's, not in DESIGN's list) — folded into the guest experience.

| # | v2 deliverable | Phase |
|---|---|---|
| 1 | Simple accounts (register/login), default **guest** role, manual tenant promotion | P1 |
| 2 | Guest experience — welcome page (rules-as-menu, Hall of Shame, behave/report/pay) | P2 |
| 3 | **Getting here** — map (native chooser) + copy address + Uber/Ola ride links | P3 |
| 4 | Tenant gating (dashboard behind login) + NFC `/s/<spot>` routes (role decides the view) | P4 |

Guest **self-pay** (wallet QR + mark-paid) sits in P2 with the rest of the guest experience.

Deferred to v3 (unchanged): dispute voting / loser-pays, month-end settle, auto money-ingest, tenant invite/leave flow.

---

## Deployment Strategy & Data Migration

Same single FastAPI process + one SQLite file. **Migration:** v2 adds `username`/`password_hash` to `members` via an idempotent `ALTER TABLE ... ADD COLUMN` (guarded by `PRAGMA table_info`) in `db.py` bootstrap — no migration framework, no "delete the db." `schema.sql` updated so fresh DBs get the columns directly.

## Decisions (previously open questions — now settled)

- **Accounts:** plain **username + password** self-registration. Password hashed with stdlib `hashlib.scrypt`; session is an HMAC-signed cookie (no heavy deps).
- **Default role = guest;** an existing tenant promotes someone to `tenant` **manually** (a tiny admin helper / documented one-liner — no self-service elevation).
- **Role mechanism:** the existing `members.role` TEXT column. No roles table / roleId.
- **No magic-link tokens, no separate guest login** — guests are just logged-in users with the guest role.
- **Getting here is config-driven** — address + coordinates from `.env`; degrades gracefully if unset.

## Out of Scope (v2)
- ❌ OAuth / email-verification / password reset flows (a friends' flat; keep it minimal).
- ❌ Moving money (wallet QR + mark-paid only).
- ❌ Voting / settle / auto-ingest / tenant invite-leave (all v3).

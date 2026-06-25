# Hive — v2 — Business Rules

> **Plan folder:** `plans/v2/`
> **Status:** DRAFT — simple-accounts model + Getting here.
> **Related:** [overview](overview.md) · [requirements](requirements.md) · [data-dictionary](data-dictionary.md) · [api-surface](api-surface.md) · [shared-definitions](shared-definitions.md) · [task-summary](task-summary.md)

Testable assertions. `_Source:_` REQ + `_Enforced by:_` mechanism. v1's BR-0xx still hold (esp. BR-000 no-money-movement, BR-003 snapshot, BR-031/032 cooling window, BR-060/061 boot/webhook).

## Accounts & roles

- **BR-A01:** Self-registration creates an active member with **`role='guest'`** by default.
  _Source:_ REQ-A-001 [User] _Enforced by:_ `/register` → `register_member()`, which writes `role='guest'` (+ username/password_hash).
- **BR-A02:** `username` is required, unique case-insensitively; duplicate registration is rejected.
  _Source:_ REQ-A-001/005 [User/Inferred] _Enforced by:_ functional `lower(username)` unique index + pre-insert check.
- **BR-A03:** Promotion to `tenant` is an **out-of-band admin step**, the **only** path to the tenant role — no HTTP/self-service route ever writes `'tenant'` (registration always writes `'guest'`).
  _Source:_ REQ-A-002 [User] _Enforced by:_ a documented admin CLI (`python -m app.admin promote <username>`) that sets `role='tenant'`; no web route mutates role.
- **BR-A04:** Role is the existing `members.role` TEXT — no roles table, no numeric roleId.
  _Source:_ REQ-A-003 [User] _Enforced by:_ reuse of the v1 column + CHECK.
- **BR-A05:** Passwords are never stored in plaintext — hashed with **bcrypt** (per-hash salt built in); verification is constant-time.
  _Source:_ REQ-A-004 [Inferred] _Enforced by:_ `bcrypt.hashpw` / `bcrypt.checkpw` (standard library, not hand-rolled crypto).
- **BR-A06:** A session is a Starlette `SessionMiddleware` signed cookie carrying the member id; tampering invalidates it; logout clears it.
  _Source:_ REQ-A-004 [Inferred] _Enforced by:_ `SessionMiddleware` (key = `SECRET_KEY`/`WEBHOOK_SECRET`); startup warns on the default key.

## What the role changes (only two things)

- **BR-R01:** Only active **tenants** are snapshotted into `bill_shares`; a guest never owes rent.
  _Source:_ REQ-R-001 [Explicit] _Enforced by:_ `create_bill_with_shares` iterates `list_active_tenants` (v1, unchanged).
- **BR-R02:** The dashboard `/` requires **tenant** role (guests → `/me`, logged-out → `/login`). Management actions (create bills, manage rules) are bot/admin-CLI only — there are no web write-routes for them.
  _Source:_ REQ-R-002 [Explicit] _Enforced by:_ `require_tenant` dependency on `GET /`.
- **BR-R03:** Fining, reporting, paying, dues, and pot math are **role-agnostic** — guests and tenants are treated identically there. Guests ARE finable, so the `/fine` accused picker includes active guests.
  _Source:_ REQ-R-003 [Explicit] _Enforced by:_ shared `fines` service + picker over active members (tenants + guests), excluding the reporter.

## Guest experience

- **BR-G01:** The welcome page shows a personalized hello, rules-as-menu, Hall of Shame, and behave/report/pay.
  _Source:_ REQ-G-001 [Explicit] _Enforced by:_ `welcome.html` from the member + v1 rules/overturn data.
- **BR-G02:** A guest report creates a normal `pending` fine (cooling window applies; accused active; no self-fine), `added_by` = the guest.
  _Source:_ REQ-G-002 [Explicit] _Enforced by:_ web action → `fines.create_fine` (reuses BR-031/034).
- **BR-G03:** "Pay" shows the wallet UPI QR + the member's unpaid owed fines and records a **claim** via `fines.mark_paid` (only `confirmed`/`upheld`). Never moves money.
  _Source:_ REQ-G-003 [Explicit] _Enforced by:_ reuse of v1 `mark_paid` (BR-036) + read-only QR (BR-000).
- **BR-G04:** Every web action is scoped to the **logged-in** member id (from the session), never an id in the request body.
  _Source:_ REQ-G-004 [Inferred] _Enforced by:_ acting member resolved from the session cookie only.

## Getting here

- **BR-L01:** The map action opens the location in the **guest's own** map app where possible (a `geo:`/maps link that triggers the native app chooser), not a single hard-coded provider.
  _Source:_ REQ-L-001 [User] _Enforced by:_ a `geo:<lat>,<lng>` / universal maps URL link + a "Directions" link.
- **BR-L02:** The address is shown and **copyable in one tap** in a cab-app-ready text form.
  _Source:_ REQ-L-002 [User] _Enforced by:_ address text + a clipboard-copy button (client-side JS).
- **BR-L03:** Ride options pre-fill the flat as the **drop**: Uber + Ola deep links are shown; Rapido falls back to copy-address. Exact deep-link params are verified at build (P3).
  _Source:_ REQ-L-003 [User] _Enforced by:_ Uber/Ola deep-link buttons built from `FLAT_LAT`/`FLAT_LNG`/`FLAT_PLACE_NAME`.
- **BR-L04:** With no location config, Getting here degrades gracefully (address-only, or the section is hidden) — never a broken map/link.
  _Source:_ REQ-L-004 [Inferred] _Enforced by:_ template conditionals on the `FLAT_*` settings.

## NFC `/s/<spot>`

- **BR-N01:** `/s/<spot>` renders the configured page for a known spot; unknown spot → 404.
  _Source:_ REQ-N-001 [Explicit] _Enforced by:_ `SPOTS` lookup.
- **BR-N02:** Each spot carries its DESIGN content incl. the rule-category pre-filter (kitchen/smoking/bathroom).
  _Source:_ REQ-N-001 [Explicit] _Enforced by:_ the `SPOTS` config.
- **BR-N03:** `/s/<spot>` is public and the role decides the view, defaulting to the *less* privileged view: the `living_room` spot redirects a **tenant** to the dashboard; every other spot renders the contextual guest page to everyone (anon → rules + login prompt; member → report form; tenant → an added Dashboard link).
  _Source:_ REQ-N-002 [Explicit] _Enforced by:_ `current_member` + the per-spot role branch in `GET /s/<spot>`.

## Platform

- **BR-P01:** `members` gains `username`/`password_hash` via idempotent `ADD COLUMN` guarded by `PRAGMA table_info`.
  _Source:_ REQ-P-001 [Inferred] _Enforced by:_ `db.py` check-then-alter + updated `schema.sql`.
- **BR-P02:** Web boots with no bot token (BR-060); pay omits the QR if unset; Getting here degrades if location unset.
  _Source:_ REQ-P-002 [Inferred] _Enforced by:_ settings-conditional templates.

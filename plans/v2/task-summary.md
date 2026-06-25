# Task Summary — Hive v2 (accounts + guests + getting here + NFC)

> Human-readable progress tracker. **Phases** group ordered tasks; each ends with a review gate + smoke test (as in v1).
> **DRAFT** — awaiting go-ahead before Phase 1 code.

**Plan folder:** `plans/v2/`
**Generated:** 2026-06-24 · **Revised:** simple-accounts model + Getting here
**Phases:** 4 | **Tasks:** ~12 (estimate)

---

## Phase 1: Accounts & roles

**Goal:** Self-registration with username + password; everyone starts as a guest; a tenant promotes the real flatmates manually.

| Task | Title | Type | Status | Notes |
| ---- | ----- | ---- | ------ | ----- |
| 1 | `members` migration — add `username`, `password_hash` (idempotent `ADD COLUMN` + `lower(username)` unique index) | Schema | ✅ Done | `db.py` `_migrate`; `schema.sql` updated. |
| 2 | `app/auth.py` — `hash_password`/`verify_password` (scrypt), signed session cookie, `require_login`/`require_tenant` deps | App | ✅ Done | Stdlib only; `SECRET_KEY` (falls back to `WEBHOOK_SECRET`); startup warns on default key. |
| 3 | Account queries — `register_member` (role='guest'), `get_member_by_username`, `set_role` | Repository | ✅ Done | Case-insensitive username. |
| 4 | Routes + templates — `/register`, `/login`, `/logout` | App + Web | ✅ Done | `register`/`login.html`; duplicate-insert race caught. |
| 5 | Manual promotion — admin CLI to set `role='tenant'` | App | ✅ Done | `python -m app.admin promote`; no self-elevation. |

**Verified:** `tests/smoke_auth.py` (10 checks) + the Phase 1 review gate (16→14 findings; see Review log). All 5 suites green.

### Phase 1 Review log (2026-06-24)
5-lens adversarial review, **16 raw → 14 confirmed → 5 distinct fixes, all applied:**
- **[fix-now / high]** Session forgery: the cookie-signing key fell back to the public `hive-dev-secret` (via `WEBHOOK_SECRET`), so with neither secret set, anyone could forge a session for any member id (incl. a tenant). The webhook warned on the default but only in bot mode → web-only deploys had no warning. Added an **unconditional** startup warning when `secret_key` is empty/default.
- Concurrent duplicate registration → raw `IntegrityError`/500: now caught → "username is taken" 400 (the `lower(username)` unique index is the authoritative guard; asserted in the test).
- `.env.example` now documents `SECRET_KEY`; README documents register/login + `app.admin` + `smoke_auth`.
- BR wording synced (`register_member`, out-of-band admin CLI).

## Phase 2: Guest experience

**Goal:** What a logged-in guest sees and does — welcome page, report, self-pay.

| Task | Title | Type | Status | Notes |
| ---- | ----- | ---- | ------ | ----- |
| 6 | `welcome.html` + `GET /me` — hello, rules-as-menu, Hall of Shame, behave/report/pay | Web | ✅ Done | Reuses v1 rules data + new `hall_of_shame`. |
| 7 | Guest **report** (`POST /report`) — `pending` fine via the v1 service | App | ✅ Done | Accused active; no self-fine. |
| 8 | Guest **self-pay** (`/pay`, `POST /pay/<fine_id>`) — wallet QR + mark-paid | App + Web | ✅ Done | Claim only; ownership-guarded; reuse `mark_paid`. |
| 9 | Make guests **finable** — `/fine` accused picker uses `list_active_members` | Bot | ✅ Done | Guests subject to fines (BR-R03); asserted in `smoke_bot`. |

**Verified:** `tests/smoke_guest.py` (8 checks); all 6 suites green.

### Phase 2 Review log (2026-06-24)
5-lens adversarial review, **12 raw → 7 confirmed** (all low/nit — no security/money/access/XSS bugs). Applied:
- Out-of-range int id (≥ 2⁶³) in `/report` & `/pay/{id}` → `OverflowError`/500. Fixed centrally: the id-lookups (`get_member`/`get_rule`/`get_fine`) treat an un-storable id as "not found" (future-proofs all routes). Asserted in the test.
- Session cookie gained a `Secure` flag (`COOKIE_SECURE` env, off for localhost dev); self-pay flash quoted consistently.
- Docs synced (this; README; api-surface `/me` note).

### Auth hardening (owner directive — production-ready, familiar libraries)
Per "use globally-used library functions, not hand-rolled crypto," the Phase 1 stdlib auth was **upgraded**: passwords now use **bcrypt** (`bcrypt.hashpw`/`checkpw`) and sessions use **Starlette `SessionMiddleware`** (`request.session`) — replacing the hand-rolled `scrypt$…` format and HMAC-signed cookie. `requirements.txt` adds `bcrypt` + `itsdangerous`. Docs (data-dictionary, business-rules, shared-definitions) updated.

## Phase 3: Getting here (the "very important" bit)

**Goal:** A guest can find their way to the flat from the welcome page.

| Task | Title | Type | Status | Notes |
| ---- | ----- | ---- | ------ | ----- |
| 10 | Config + `getting_here_links()` — `FLAT_ADDRESS`/`LAT`/`LNG`/`PLACE_NAME`; map (native chooser), copy-address, Uber/Ola/Rapido | App | ✅ Done | In `app/location.py` (not `nfc.py`). Deep-link formats web-verified; coords range/finite-checked; degrades if unset (BR-L04). |
| 11 | Getting-here card in `welcome.html` (+ clipboard JS) | Web | ✅ Done | One-tap copy; Navigate/Uber/Ola/Rapido buttons. |

**Verified:** `tests/smoke_location.py` (link-builder branches + `/me` render); all 7 suites green.

### Phase 3 Review log (2026-06-24)
4-lens adversarial review, **12 raw → 7 confirmed** (2 low, 5 nit — no security/correctness bugs; deep-link formats confirmed correct). Applied: literal-comma maps/geo URLs (was `%2C`); coord validation now rejects `nan`/`inf`/off-globe so it degrades cleanly (BR-L04); hint copy made conditional on an address; docs synced (this, README, shared-definitions `location.py`, api-surface).

### Owner additions (during Phase 3)
- **Rapido** ride option added. Rapido publishes **no** drop-prefill deep link (web-verified), so its button opens the Rapido app (`rapido.bike` universal link) and the rider pastes the copied address; Uber/Ola still pre-fill the drop.
- **Responsive design** — the site is now mobile + desktop friendly: wide tables scroll horizontally (`.table-wrap`) and a `≤600px` media query tightens spacing/typography and makes action buttons full-width. (viewport meta was already present.)

## Phase 4: Tenant gating + NFC

**Goal:** Dashboard behind login; stickers show the right view per role.

| Task | Title | Type | Status | Notes |
| ---- | ----- | ---- | ------ | ----- |
| 12 | Gate the dashboard `/` behind `require_tenant`; guest → `/me`, logged-out → `/login` | App | ✅ Done | Reverses v1's open dashboard (intended). |
| 13 | `app/nfc.py` SPOTS config + `GET /s/<spot>` — role decides the view; category pre-filter | App + Web | ✅ Done | 6 spots; kitchen/smoking/bathroom filters; living_room tenant → dashboard. |

**Verified:** `tests/smoke_nfc.py` (gating for anon/guest/tenant; `/s` 404; category pre-filter; living_room two-audience); all 8 suites green.

### Phase 4 Review log (2026-06-24)
4-lens adversarial review, **10 raw → 10 confirmed** (4 low, 6 nit — access control cleared: no gating bypass, no redirect loop). Applied:
- `require_tenant` wired into `/` (guest → `/me`) instead of an inline branch — removes the dead helper.
- `_fits_i64` `isinstance(int)`-guarded so a forged non-int session id is a clean logged-out miss, not a 500 (pre-existing v1 robustness gap; asserted in `smoke_auth`).
- Spot "Report" anchor gated on `rules and members` (no dead `#report` link when there's no one to fine).
- Docs synced (this, api-surface, README, BR-N03/BR-R02 wording).

**Note (intentional):** `front_door`/`fridge` render the generic spot page (pot + favorites + Pay/report) in v2; the full welcome + Getting-here card stays on `/me`. A richer per-spot welcome is a later polish, not a v2 requirement.

---

## Legend
⏳ Pending · 🟡 In progress · ✅ Completed · ⚠️ Pending verification · ❌ Fix required

## Notes
- Role does real work in only two places: **bills** (tenants only) + **access** (tenant=dashboard/manage, guest=view/report/pay). Everything else is role-agnostic.
- Each phase ends with an adversarial review gate + a `tests/` smoke test, same as v1.

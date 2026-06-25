# Hive — v2 — Shared Definitions

> **Plan folder:** `plans/v2/`
> **Status:** DRAFT — simple-accounts model + Getting here.
> **Related:** [overview](overview.md) · [requirements](requirements.md) · [data-dictionary](data-dictionary.md) · [business-rules](business-rules.md) · [api-surface](api-surface.md) · [task-summary](task-summary.md)

v1 terms (pot, dues, fine, cooling window, snapshot, OWED_STATUSES) are unchanged — see [../v1/shared-definitions.md](../v1/shared-definitions.md). New for v2:

| Term | Definition |
|---|---|
| **Account** | A member with a `username` + `password_hash` who logs in on the web. Created by self-registration. |
| **Registration** | `/register` with username + password → a new active member, `role='guest'`. |
| **Role** | The existing `members.role` TEXT: `'guest'` (default) or `'tenant'`. No roles table / roleId. Drives exactly two things: bill splits + access. |
| **Promotion** | A tenant manually flipping a member's role from `guest` to `tenant`. The only path to tenant. |
| **Guest** | A logged-in member with `role='guest'`: finable, can report/pay/view, **never** in `bill_shares`. |
| **Tenant** | A logged-in member with `role='tenant'`: in bill splits, gets the dashboard + management. |
| **Session** | Starlette `SessionMiddleware` signed cookie (`hive_session`) carrying the logged-in member id; signing key = `SECRET_KEY`/`WEBHOOK_SECRET`. Accessed via `request.session`. |
| **Getting here** | The welcome-page card that helps a guest reach the flat: map (native app chooser), copy-address, and Uber/Ola ride deep links. Config-driven (`FLAT_*`). |
| **Spot** | One of six NFC locations (`front_door`, `fridge`, `kitchen`, `balcony`, `living_room`, `bathroom`) → title + rule-category filter + view, in `app/nfc.py`. |
| **Claim of payment** | "Pay" shows the wallet UPI QR and records `paid=1` — a claim reconciled against the jar. The app still **never moves money** (v1 BR-000). |

## Representation conventions (additions)
| Thing | Representation |
|---|---|
| `password_hash` | a **bcrypt** hash string (`bcrypt.hashpw`, e.g. `$2b$12$...`); verified with `bcrypt.checkpw`. |
| `username` | case-insensitive unique (functional `lower(username)` index). |
| Session cookie | `hive_session`, `httponly` + `samesite=lax` (+ `secure` when `COOKIE_SECURE`); signed by `SessionMiddleware`. |
| Coordinates | `FLAT_LAT`/`FLAT_LNG` as decimal strings; used in `geo:` + ride deep links. |

## Code-level shared symbols (planned)
| Symbol | Location | Purpose |
|---|---|---|
| `hash_password`, `verify_password` | `app/auth.py` (new) | bcrypt hashing. |
| `login_member`, `logout_member`, `current_member`, `require_login`, `require_tenant` | `app/auth.py` | `request.session` helpers + FastAPI dependencies. |
| `register_member`, `get_member_by_username`, `set_role` | `app/queries.py` | accounts + promotion. |
| `getting_here_links(settings)` | `app/location.py` | map / copy-address / Uber·Ola·Rapido link builder. |
| `SPOTS` | `app/nfc.py` (Phase 4) | NFC spot config. |
| `templates/{register,login,welcome,pay,spot}.html` | `templates/` | new pages; reuse `base.html` + v1 CSS. |

# Hive — v2 — Data Dictionary

> **Plan folder:** `plans/v2/`
> **Status:** DRAFT — simple-accounts model + Getting here config. Keep this, `app/schema.sql`, and the v1 data-dictionary in sync.
> **Related:** [overview](overview.md) · [requirements](requirements.md) · [business-rules](business-rules.md) · [api-surface](api-surface.md) · [shared-definitions](shared-definitions.md) · [task-summary](task-summary.md)

## 1. New SQL tables
**None.** No roles table — the role is the existing `members.role` TEXT (`'guest'`/`'tenant'`).

## 2. Changed table — `members` (two new columns)
| Column | Type | Notes |
|---|---|---|
| `username` | TEXT UNIQUE | Chosen at registration; case-insensitive unique. Login identity. NULL for v1 bot-only members until/unless they register. |
| `password_hash` | TEXT | **bcrypt** hash string (`bcrypt.hashpw`, e.g. `$2b$12$...`). NULL for members who never set a web password. |

`members.role` already exists (`'tenant'`/`'guest'`, CHECK). **Registration sets `role='guest'`.** Promotion = a tenant flips it to `'tenant'`.

**Migration (idempotent, in `db.py` bootstrap):**
```sql
-- run each only if absent (checked via PRAGMA table_info(members))
ALTER TABLE members ADD COLUMN username       TEXT;
ALTER TABLE members ADD COLUMN password_hash  TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_members_username ON members(lower(username));
```
`schema.sql` is updated too, so fresh DBs get the columns directly. (`ADD COLUMN` can't carry `UNIQUE`, hence the separate index; a functional `lower(username)` index gives case-insensitive uniqueness.)

> The v1 `web_token` / `expires_on` idea is **dropped** — accounts replace magic-link tokens.

## 3. New config — env (not DB)
| Setting | Purpose |
|---|---|
| `SECRET_KEY` | Signs the session cookie (HMAC). Falls back to `WEBHOOK_SECRET` if unset. |
| `FLAT_ADDRESS` | Human address shown + copied on the Getting-here card (cab-app-ready text). |
| `FLAT_LAT`, `FLAT_LNG` | Coordinates for map + ride deep links (most reliable for cabs). |
| `FLAT_PLACE_NAME` | Optional label/nickname for the drop (e.g. "Hive"). |
| `WALLET_UPI_QR_URL` | (already in v1 `.env.example`) the pay screen's QR. |

All optional at boot; the relevant UI degrades gracefully when unset (BR-L04, BR-P02).

## 4. NFC spots — code config, not a table
Six spots in `app/nfc.py` (data, like `seed.py`): `front_door`, `fridge`, `kitchen`, `balcony`, `living_room`, `bathroom` → `{title, rule-category filter, view}`. (kitchen→`kitchen` rules, balcony→`smoking`, bathroom→`bathroom`.)

## 5. Derived / session
| Value | Definition | Where |
|---|---|---|
| Logged-in member | resolved from the signed session cookie → member id | auth dependency |
| Is tenant? | `member.role == 'tenant'` | gate dashboard/management |
| Guest active? | `is_active = 1` (no expiry column in this model) | pickers, login |

## 6. Unchanged invariants (still load-bearing)
- `bill_shares` = point-in-time snapshot over **active tenants only**; guests never in a split (v1 BR-003/041).
- Fine `status` workflow + pot/dues calcs unchanged; guest fines flow through the same `fines` service.

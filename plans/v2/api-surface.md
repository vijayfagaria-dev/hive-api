# Hive — v2 — API Surface

> **Plan folder:** `plans/v2/`
> **Status:** DRAFT — simple-accounts model + Getting here.
> **Related:** [overview](overview.md) · [requirements](requirements.md) · [data-dictionary](data-dictionary.md) · [business-rules](business-rules.md) · [shared-definitions](shared-definitions.md) · [task-summary](task-summary.md)

Builds on v1's surface ([../v1/api-surface.md](../v1/api-surface.md)). New web pages are session-based; the role gates what's shown.

## 1. Auth routes
| Method | Path | Purpose |
|---|---|---|
| GET | `/register` | Registration form. |
| POST | `/register` | Create member (`role='guest'`, hashed password) → set session → redirect (BR-A01/02/05). |
| GET | `/login` | Login form. |
| POST | `/login` | Verify username + password → set signed session cookie (BR-A06). |
| POST | `/logout` | Clear the session cookie. |

## 2. Guest experience (logged in)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/me` (or `/`) for a guest | session | **Welcome** page: hello, **Getting here**, rules-as-menu, Hall of Shame, behave/report/pay (BR-G01). |
| POST | `/report` | session | Report a fine → `pending` via the v1 `fines` service (BR-G02). |
| GET | `/pay` | session | Pay screen: wallet UPI QR + the member's unpaid fines (BR-G03). |
| POST | `/pay/<fine_id>` | session | Mark **their own** fine paid — a claim (BR-G03/G04). |

A logged-in **tenant** hitting `/` gets the v1 dashboard; a logged-in **guest** gets the welcome page. Not logged in → redirect to `/login` (or guest view for `/s/<spot>`).

> **Live (Phase 4):** role-based `/` routing is in place — the dashboard is **tenant-gated** (`require_tenant`): logged-out → `/login`, guest → `/me`, tenant → dashboard.

## 3. Getting here (rendered into the welcome page, not separate routes)
Built from `FLAT_ADDRESS` / `FLAT_LAT` / `FLAT_LNG` / `FLAT_PLACE_NAME`:
| Element | How |
|---|---|
| **Open in Maps** | link to `geo:<lat>,<lng>?q=<lat>,<lng>(<place>)` (native chooser) + a `https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>` "Directions" link |
| **Copy address** | the address text + a one-tap clipboard-copy button (client JS) |
| **Uber** | `https://m.uber.com/ul/?action=setPickup&dropoff[latitude]=<lat>&dropoff[longitude]=<lng>&dropoff[nickname]=<place>` |
| **Ola** | `https://book.olacabs.com/?...drop_lat=<lat>&drop_lng=<lng>...` (deep link) |
| **Rapido** | opens the Rapido app (`https://www.rapido.bike/` universal link) — Rapido has **no** public drop-prefill deep link (web-verified), so the rider pastes the copied address |

> Built in `app/location.py::getting_here_links(settings)`. Deep-link formats web-verified 2026-06 against Uber/Ola docs (Uber + Ola pre-fill the drop; Rapido opens the app). Coords are finite/range-checked; the card degrades to address-only or hidden when unset (BR-L04).

## 4. NFC
| Method | Path | Purpose |
|---|---|---|
| GET | `/s/<spot>` | Public contextual spot page; the role decides the view (BR-N03). The `living_room` ("control room") spot redirects a **tenant** to the dashboard; every other spot shows the contextual page to everyone — anon gets rules + a "log in to report/pay" prompt, a logged-in member gets the report form (pre-filtered to the spot's category), and a tenant additionally gets a Dashboard link. Unknown spot → 404. |

## 5. Bot surface (additions)
| Command | Does |
|---|---|
| `/fine` accused picker | Now includes **active guests** as well as tenants (guests are finable, BR-R03). |
| (promotion) | Promoting a guest → tenant is a **manual admin action** (a tenant-gated helper / documented one-liner), not a public route. |

## 6. Unchanged from v1
`/health`, `POST /telegram/webhook/<secret>`, the sweep job, and all v1 bot commands/callbacks. No money-movement routes (BR-000). Magic-link guest tokens are **not** used (replaced by accounts).

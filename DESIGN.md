# 🏠 Hive — Flat Fine & Bills Bot

> Single source of truth for the project. This is the distilled output of the
> whole design conversation. Read this first before writing any code.

## What it is

A **personal Telegram bot** that runs a shared flat for 4–6 friends: it holds the
house rules, logs fines, tracks a common "fine pot," splits the four recurring
bills, and chases dues until they're paid. Plus a delightful guest experience and
tap-to-open NFC stickers around the flat.

**The one principle that drives every decision:**

> **The bot is the *ledger*, the wallet is the *jar*, and the two only ever touch read-only.**
> The app records and calculates. It never holds or moves money.

## Why we built our own (instead of an existing app)

The exact combo we want — a neutral fine pot + our own rules/fines + only four
specific bills + dues + one-tap logging + guest access + NFC — isn't sold as a
single product. Every off-the-shelf tool (Splitwise, Grist, Notion, neobank jars)
nails one slice and misses the rest. So: build it, own it, ₹0 to run.

## Money: custody vs tracking (the hard rule)

- **Custody** = a throwaway "fridge-QR" wallet (a fresh Fi/Jupiter/Paytm account
  used *only* for the pot). It physically holds the fine cash. Neutrality comes
  from it being nobody's personal account + full transparency, not from tech locks.
- **Tracking** = this app. It gets **read-only** sight of money arriving and
  updates the ledger.
- **We do NOT build a wallet.** Holding INR in custody is RBI-licensed PPI territory.
- **Account Aggregator** (India's official read-only banking rail) is perfect in
  theory but **closed to individual devs** (only RBI/SEBI/IRDAI/PFRDA-regulated
  entities can be a Financial Information User). Ruled out.
- **Read-only ingestion options**, in order of preference:
  1. **Manual** — the `/fine` action *is* the record; reconcile against the wallet
     weekly. (Start here.)
  2. **SMS forwarding** — a forwarder (MacroDroid/Tasker) on the wallet phone POSTs
     bank-credit SMS to the app; it parses the amount + UPI note and ticks the fine paid.
  3. **Email receipts** — Gmail API on the read-only scope parses wallet emails.
  - Optional "real API" path: collect via a payment gateway (Razorpay/Cashfree)
    instead of a raw wallet — but that adds KYC/fees. Overkill for a small pot.
- **Paying in (the outbound half).** The Pay screen builds a **UPI request** to the
  throwaway wallet's VPA (`UPI_VPA`): a scannable QR (the generic `upi://pay?...`
  intent, amount pre-filled) plus one-tap **Google Pay / PhonePe / Paytm** deep
  links. This is still **no-custody** — we only *format* the request; the rupees
  move bank-to-bank inside the payer's own UPI app, straight to the jar. Built in
  `domain/upi.py` + `schemas/payments.py`; unset `UPI_VPA` → the screen shows a
  "not set up" state. Confirming the money arrived is the read-only half above.

## Stack (decided)

| Piece | Choice | Notes |
|---|---|---|
| Hosting | **Oracle Cloud Always Free** VM | Real Linux box, free *forever*, runs bot + DB on one machine |
| Backend / API | **FastAPI** (Python 3.11+) | Telegram webhook + a **JSON API** at `/api/*` (`app/api.py`) consumed by the frontend |
| Bot lib | **aiogram 3** | Async, pairs cleanly with FastAPI |
| DB | **SQLite** (via `aiosqlite`) | Tiny, zero-maintenance; 100 rules / years of data is nothing |
| Frontend | **Next.js 16** (App Router, TypeScript) | `frontend/` — Tailwind v4 + shadcn (Base UI) + Framer Motion + TanStack Query + Zod contract; Next proxies `/api` → FastAPI (same-origin cookie auth). _(Supersedes the original Jinja2 plan — see note below.)_ |
| Money | Throwaway fridge-QR wallet | Read-only link via SMS/email parse (or manual) |

> **Architecture note (updated):** the web UI was originally Jinja2 templates rendered by FastAPI. It is now a standalone **Next.js frontend** (a deliberate, product-owner-driven upgrade for a polished, animated experience). FastAPI kept all its logic and simply gained a JSON API; the Jinja routes are retired once the frontend fully replaces them.

Alternative hosting if you'd rather not babysit a VM: **Cloudflare Workers + D1**
(serverless, never sleeps — but bot would be JS). **Railway** is easiest deploy
(~$0–5/mo credit, no cold starts). Avoid Render free (spin-down) and Supabase as
the sole DB (pauses after 7 days idle).

## The two faces (one backend)

```
   Telegram chat  ─┐
   (tap buttons)   │
                   ├──►  ONE FastAPI app  ──►  SQLite
   Web pages      ─┘            │
   (dashboard,                  └──►  reads wallet credits (SMS/email, read-only)
    guest, NFC)
```

- **Bot** = the fast lane for *input* and quick checks. Tap-driven (inline
  keyboards), not command-memorizing. Lives in the flat's group chat. Free push
  notifications.
- **Dashboard / web** = the *overview & management* (tables, history, editing the
  100-rule list, month-end settle). The thing chat is bad at.
- Both read the same SQLite, so they're never out of sync.

**Open decision:** dashboard as a **Telegram Mini App** (opens inside Telegram,
reuses Telegram identity, no login to build — *recommended*) vs a **standalone
web page / PWA** (bookmark, but build a tiny login).

## Backend architecture (layered)

The backend is a layered FastAPI app over **SQLAlchemy 2.0 async ORM** + **Alembic**
(`sqlite+aiosqlite`). Strict boundaries keep it growable:

```
api/ (routes + deps)  →  services/ (business logic)  →  repositories/ (ORM queries)  →  db/models
   ▲ schemas/ (DTOs)         ▲ domain/ (enums, time)        core/ (config, logging, errors, security)
```

- **Routes** handle only request/response and delegate to services.
- **Services** own the rules (complaint workflow, the bill-share snapshot, accounts,
  reporting, notifications) and raise semantic errors mapped centrally to HTTP.
- **Repositories** hold all ORM queries and **never commit** — the request is one
  unit of work (`get_session`); the sweep/CLI use `session_scope`.
- **Models** (`db/models/`) are the schema of record; **Alembic** migrations evolve
  it (`create_all` self-provisions fresh/dev DBs). Timestamps stay TEXT ISO-8601.

## Data model

```sql
members (
  id, name, telegram_id,   -- telegram_id is legacy (bot retired in v4)
  username, password_hash, -- v2 web login
  email,                   -- v4 optional; email notification fallback
  role,            -- 'tenant' | 'guest'
  is_active,       -- in the house right now?
  joined_on, left_on,
  host_id          -- which tenant invited this guest (null for tenants)
)

rules (
  id, category, text, fine_amount,
  is_favorite,     -- surfaces as a quick button in the bot
  use_count,       -- self-tunes: most-fined rules bubble up
  severity_tier,   -- low fines = lazy-consensus; high = needs confirm/vote
  auto_confirm
)

fines (
  id, member_id, rule_id, amount, ts,
  added_by,        -- who reported it (accuser accountability)
  status,          -- 'pending' | 'confirmed' | 'disputed' | 'void' | 'upheld'
  paid,
  confirm_deadline,
  dispute_reason,
  vote_deadline,   -- v3: set when a vote opens; auto-finalizes after this
  resolution,      -- v3: 'accepted' | 'auto_confirmed' | 'upheld' | 'void'
  resolved_at      -- v3: terminal timestamp
)

fine_votes (id, fine_id, voter_id, vote, ts)   -- for disputed (voting) complaints

-- v3 complaint workflow (see "Complaint workflow" below)
fine_proofs (id, fine_id, uploaded_by, source, ref, content_type, width, height, ts)
fine_events (id, fine_id, type, actor_id, detail, ts)         -- append-only audit trail
notifications (id, member_id, kind, title, body, fine_id, read, ts)  -- in-app backbone
complaint_drafts (id, reporter_id, source, ref, content_type, caption, ts)  -- legacy bot staging (unused in v4)
push_subscriptions (id, member_id, endpoint, p256dh, auth, ts)  -- v4 Web Push (VAPID)

-- v5 rule proposals (community vote to change the rule book)
rule_proposals (id, proposer_id, type, status, target_rule_id, title, body,
  proposed_category, proposed_text, proposed_amount, voting_opens_at, voting_closes_at,
  frozen, resolved_at, resolution_detail, merged_rule_id, merged_rule_version_id,
  created_at, updated_at, version)            -- version = optimistic lock
proposal_votes (id, proposal_id, voter_id, choice, ts)   -- UNIQUE(proposal_id, voter_id)
proposal_comments (id, proposal_id, author_id, parent_id, body, edited_at, deleted, created_at)
proposal_events (id, proposal_id, type, actor_id, detail, ts)   -- append-only timeline
rule_versions (id, rule_id, version_number, <rule snapshot>, active, created_by,
  approved_by, proposal_id, created_at)       -- immutable rule history; rollback = new version
rules (… , is_active)                          -- v5: a deleted rule is deactivated, never row-deleted

bills (id, type, total, month, paid_by, ts)   -- type: rent|house_help|electricity|water

bill_shares (id, bill_id, member_id, share_amount, paid)   -- POINT-IN-TIME SNAPSHOT
```

**Pot** = `sum(fines.amount where status='confirmed'/'upheld')` minus what's applied to rent.
**Dues** = unpaid confirmed fines + unpaid bill_shares.

## Roles & lifecycle

- **Tenant** = full member: in rent/bill splits, can fine anyone, pay, manage rules.
- **Guest** = lightweight, temporary: subject to fines, can view rules / report /
  pay — but **NOT in rent/bill splits** (guests don't pay rent). Removable / expiring.
- Keep permissions flat for 4 friends — every tenant can do everything; add an
  admin role only if you ever need one.

**The one gotcha that matters — splits must be point-in-time.** Never compute
`rent ÷ count(active tenants)` live, or adding a 5th person silently rewrites
everyone's *past* rent. On each bill, **snapshot** one `bill_shares` row per
currently-active tenant. June stays ÷4 forever even after July splits ÷6.
**Build `bill_shares` in from v1 — it's the one thing you can't cleanly retrofit.**

## Picking 1 rule out of 100 (selection at scale)

Storing 100 rules is trivial (SQLite). The challenge is *selecting* one fast.
Never show 100 buttons. Four tricks:

1. **Favorites first** — ~10 ⭐ rules cause 90% of fines; show them as quick buttons.
2. **Browse by category** — 8 categories × ~12 rules, drill-down.
3. **Search / inline type-ahead** — Telegram inline mode, scales to 1000 rules.
4. **Fuzzy text fallback** — `fine rohit dishes` matches and confirms.

Plus the slick one: **NFC location pre-filters the rules** (see below) — tap the
sticker where the crime happened and only that spot's rules show.

Managing the 100 rules = a searchable, categorized **table on the dashboard**
(literally the Excel sheet, imported once). Never manage 100 rules in chat.

## Handling fine-system abuse (frivolous / "for fun" reports)

Core principle: **a reported fine is a *claim*, not a *verdict*.** Make the honest
path frictionless, the abusive path visible and costly, and let humans resolve.
Keep *disputing* one tap (if contesting is expensive, people pay unjust fines —
which rewards the abuser). Five layers; most reports settle at Layer 1:

1. **Cooling window + lazy consensus** — a pending fine auto-confirms after ~12–24h
   *unless* the accused (or anyone) taps **Dispute**. Real fines sail through;
   joke fines get frozen.
2. **Dispute → neutral majority vote** — members who are neither reporter nor
   accused tap Uphold/Void. Tie/no-quorum → **void** (benefit of the doubt).
3. **Accuser accountability** (the anti-spam teeth):
   - **Loser-pays** — a voted-down fine flips into a "false alarm" fine on the *reporter*.
   - **Public overturn rate** — everyone sees each member's reports filed/upheld/overturned.
   - **Lose the fast-lane** — high overturn rate → all your fines require a vote up front.
4. **Rate limits & severity tiers** — cap reports/person/day; no repeat fine on the
   same person+rule within a few hours; small fines auto-confirm, big fines need a
   co-sign or vote.
5. **Human layer** — monthly meeting (over beers) clears disputes, reviews the
   overturn leaderboard, retunes rules. Meta-rule: *abusing the system is the most
   expensive fine of all.*

**Recommended starting config:** ≤₹50 auto-confirm after 12h unless disputed;
>₹50 needs accept-or-one-cosign within 24h else vote; overturned report = ₹50 on
the reporter + logged to their stat; max ~5 reports/person/day; no repeat
person+rule within 6h; overturn rate >40% → all fines need a vote.

**Honest meta-point:** you can't fully solve this in software and shouldn't try —
among friends, a public "biggest false-reporter 🏆" stat does more than any
algorithm. Ship Layer 1 + visible overturn stat + loser-pays first; add voting
only if someone games it.

## Complaint workflow (v3 — implemented)

The fine *is* the complaint. A complaint now requires **mandatory image proof**
and runs this state machine (`app/fines.py` is the single home for it):

```
                       accused taps Accept
   raised ──────────────────────────────────────► REGISTERED (status=confirmed)
  (pending)                                         resolution=accepted
     │                                         ▲
     │ accused/anyone taps Deny ──► vote opens │ cooling window elapses untouched
     ▼   (status=disputed + vote_deadline)     │ (sweep) resolution=auto_confirmed
   VOTING ──── majority Uphold ───────────────►┘ REGISTERED (status=upheld)
     │  └───── majority Void / tie / no quorum ──► REJECTED (status=void)
     ▼  (finalizes when all eligible vote, or vote_deadline passes)
```

- **Proof first.** `fines.create_fine` refuses without ≥1 `fine_proofs` row. Web =
  `POST /api/complaints` multipart (≥1 image), camera-first on mobile. No proof, no
  complaint. (A v3 Telegram photo-first flow existed but was retired with the bot in v4.)
- **Voting only when needed.** Eligible voters = active members who are neither
  accuser nor accused. Accept skips voting entirely; silence auto-confirms (the v1
  cooling window, preserved). The status enum is unchanged — "voting" is
  `status=disputed` + an open `vote_deadline`.
- **Audit trail.** Every step appends a `fine_events` row (raised, accused_notified,
  accepted, disputed, voting_started, members_notified, vote_cast, vote_finalized,
  auto_confirmed, paid) → the API timeline/status tracker.
- **Notifications** (`app/notify.py`, web-first since v4): in-app `notifications`
  row (always, the reliable backbone) + best-effort **Web Push** (VAPID; Android +
  installed iOS PWAs) + best-effort **email** fallback + best-effort **WhatsApp**
  (official Meta Cloud API, template messages — `whatsapp_enabled` when a token +
  phone-number-id are set). No Telegram. Accused is notified on raise; all eligible
  voters on a deny; both parties on resolution. Sweeps run on `SWEEP_INTERVAL_SECONDS`.
- **Anti-spam** (config): per-day complaint cap + same accused+rule dedupe window.

> **v4 — bot retired, web-first.** Telegram penetration in India is low, so the
> Telegram bot (input *and* push) was removed. The product is now the Next.js web
> app over this JSON API; the bot's management actions are API endpoints
> (`POST /api/complaints` filing, `POST /api/bills`, etc.). Notifications moved to
> the free, cross-platform stack above. `notify.py` is channel-pluggable; the
> official **WhatsApp Cloud API** is wired as one channel (template messages; the
> free dev tier fits a small flat — set `WHATSAPP_*`), beside in-app/Web Push/email.

## Rule proposals (v5 — community vote to change the rule book)

The rule book isn't edited by fiat — it's amended by a vote. Anyone can propose a
**new / modify / delete** rule; it runs a configurable voting period; if it passes,
it's auto-merged into `rules`.

```
   draft ─submit─► (pending_review ─admin approve─►) voting ─close─► passed | rejected | expired
                                                                         └ passed ⇒ merged into rules + an
                                                                            immutable rule_versions snapshot
```

- **Who votes:** active **tenants**, one vote each (yes/no/abstain), changeable until
  the deadline (`proposal_votes` UNIQUE(proposal_id, voter_id) + an optimistic-lock
  `version` on the proposal). Guests can propose + comment but not vote.
- **Passing conditions (config):** at close → `participation ≥ PROPOSAL_QUORUM` AND
  `yes-share ≥ PROPOSAL_PASS_PCT` AND `yes ≥ PROPOSAL_MIN_YES`, else rejected
  (or expired with no quorum). `PROPOSAL_REQUIRE_REVIEW` optionally gates voting
  behind an admin approval.
- **Merge + versioning:** a passed proposal creates/updates/deactivates the rule and
  appends a `rule_versions` row (rules are never silently overwritten; rollback =
  appending a new version from an old snapshot). "Delete" deactivates (`rules.is_active`)
  so fines that reference the rule keep their FK + history.
- **Reuses the existing patterns:** layered repo/service/schema/route, the
  `proposal_events` timeline (like `fine_events`), the in-app+push+email+WhatsApp
  notifier, the background **sweep** (closes elapsed votes alongside complaints), and
  session-cookie auth (admin = tenant). Comments are flat + soft-delete + edit;
  nesting/reactions/mentions and a normalized RuleCategory are a deliberate phase 2.

## The delight layer 😄

**Guest welcome page** (shared link or NFC tap): personalized welcome ("Amit's told
us you're trouble 😏"), a few flat photos, a fun **Hall of Shame** leaderboard,
rules written like a menu (emojis + amounts), and actions: *I'll behave / Report /
Pay*. Optional flexes: a "guest pass" card, a "days survived without a fine" counter.
It's a templated HTML page off the same backend.

**NFC stickers** around the flat (~₹300 for a pack of NTAG213 stickers, written
once with the free "NFC Tools" app and locked):

| Spot | Tap → opens | Clever bit |
|---|---|---|
| 🚪 Front door | Guest welcome page | Instant smile on arrival |
| 🧊 Fridge | Pay screen + pot status | Money lives where snacks live |
| 🚰 Kitchen sink | Report a fine, **pre-filtered to kitchen rules** | Location = category filter |
| 🚬 Balcony | Smoking rules + report | Tap right where it happens |
| 📺 Living room | Full dashboard / Hall of Shame | The "control room" tap |
| 🚽 Bathroom | Cleanliness rules + report | Self-explanatory |

- Android reads NFC URLs by default; iPhone XS+ reads them natively (tap → banner → Safari). No app needed.
- Each sticker holds a URL like `hive.app/s/kitchen`; the backend route `/s/<spot>`
  renders that spot's contextual page. Same sticker shows the **dashboard to a
  logged-in tenant** and the **guest view to a stranger**.

## Build order

1. **v1 (MVP):** tenants only · rules + favorites/categories/search · `/fine` →
   pot · bill split with **`bill_shares` snapshots from day one** · dues ·
   `/pot` `/dues`. Fine workflow = Layer 1 (cooling window) + visible overturn stat.
2. **v2:** guest role + read-only guest welcome page + guest self-pay · NFC `/s/<spot>` routes.
3. **v3:** add/remove-tenant invites + leave flow · dispute voting + loser-pays +
   reputation downgrade · month-end auto-summary · auto read-only money ingest (SMS/email).

Don't gold-plate. Ship v1; add the rest only if you're still using it.

## Explicit non-goals

- ❌ The app holding/moving money (RBI-licensed territory — the wallet does custody).
- ❌ Account Aggregator (closed to individual devs).
- ~~❌ A heavy frontend framework — Jinja2 pages + the bot are the whole UI.~~ **(reversed)** — the web UI is now a polished **Next.js** frontend over the FastAPI JSON API. The Telegram bot remains a first-class, separate input surface.
- ❌ Splitting arbitrary expenses — only rent, house help, electricity, water.
- ❌ A courtroom for 4 friends — social pressure is the real enforcer.

## Still open / TODO before scaffolding code

- [ ] Dashboard as **Telegram Mini App** vs standalone web page (lean: Mini App).
- [ ] Paste the actual **rules + fines list** (or the Excel) to seed `rules`.
- [ ] Pick the flat name (placeholder: "Hive") + grab a domain or use a free subdomain.
- [ ] Create the throwaway wallet + grab its UPI QR.
- [ ] Create the Telegram bot via @BotFather, get the token.

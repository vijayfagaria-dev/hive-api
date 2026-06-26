# 🐝 Hive — Frontend Implementation Brief (for Claude)

> This is the build spec for the **Hive web app** (`hive-web`). It is the single
> source of truth for the product, the API contract, and the design direction.
> You (Claude) are the implementer **and** the designer.

---

## 0. Prompt to Claude — read this first

You are building the **Hive frontend**: a mobile-first, installable **PWA** for a
4–6 person shared flat. The backend is a FastAPI JSON API (`/api/*`) that already
exists and must not change. Your job is to design and implement the entire web app
against it.

**Operating rules:**

1. **This document is your contract.** Build to the endpoints, types, enums, and
   workflow rules described below.
2. **When anything is unclear or you need exact behavior, READ THE BACKEND.** It
   lives at `../hive-api` (repo `vijayfagaria-dev/hive-api`). Don't guess field
   names, status codes, or business rules — verify them in:
   - `app/api/routes/*.py` — every route, its auth, request, and response.
   - `app/schemas/*.py` — the exact JSON field names (response mappers) and request bodies.
   - `app/domain/enums.py` — statuses, phases, vote values, bill types, the PHASE map.
   - `app/services/complaints.py` — the complaint state machine (accept/deny/vote/cooling/finalize).
   - `app/services/notifications.py` — notification kinds + channels.
   - `app/domain/nfc.py` — NFC spot config.
   - `DESIGN.md` and `CLAUDE.md` — product intent and house rules.
   If the doc and the code ever disagree, **the code wins** — and note the drift.
3. **You have full design authority.** Decide and design the screens, modules,
   popups/sheets, navigation, components, motion, and the gen-z visual language.
   Make confident, modern choices. Don't stop to ask about trivia (colors, copy,
   layout) — just build something polished and cohesive. Only surface a question
   if a real product decision is genuinely ambiguous *and* not answerable from the code.
4. **Preserve the API contract exactly.** Same-origin cookie auth; never invent
   endpoints. If you need data the API doesn't expose, note it as a backend ask
   rather than faking it.
5. **Ship incrementally** in the milestone order in §16. Keep components small,
   typed, and accessible. Every server response goes through a Zod schema. Handle
   every loading / empty / error state. It must feel great on a phone.

---

## 1. What Hive is

A flat runs on **house rules**. Break one and a flatmate files a **complaint**
(with a **mandatory photo as proof**). The accused can **Accept** (it's registered
instantly) or **Deny** — which opens a **vote** for the neutral flatmates; majority
rules, ties drop it. Ignored complaints **auto-confirm** after a cooling window.
Registered complaints become **fines** that fill a shared **"pot."** The app also
splits four recurring **bills**, tracks **dues**, has a **pay** screen (read-only —
it never moves money), a **Hall of Shame** leaderboard, **NFC spot** pages, and a
guest welcome experience.

Two roles: **tenant** (full member) and **guest** (lightweight; finable, can pay,
not in bill splits, no dashboard). Notifications go out **in-app + Web Push + email
+ WhatsApp**.

**Vibe:** a toy for friends — playful, fast, a little chaotic, very mobile.

---

## 2. Tech stack & setup

Per `DESIGN.md` the frontend is **Next.js (App Router, TypeScript)** with:
- **Tailwind v4** + **shadcn/ui (Base UI)** for components.
- **Framer Motion** for motion/micro-interactions.
- **TanStack Query** for all server state (caching, optimistic updates, refetch).
- **Zod** for runtime-validated API contracts (one schema per response).
- **PWA**: web manifest + service worker (installable, Web Push).

**Auth is same-origin cookie.** Configure Next to **proxy `/api/*` → the FastAPI
backend** (e.g. `next.config` rewrites to `http://localhost:8000/api/:path*` in dev,
and the real origin in prod) so the `hive_session` cookie is first-party. Always
send credentials (`fetch(..., { credentials: "include" })` or an axios instance with
`withCredentials`). Never put a token in JS — it's a signed httpOnly-style session cookie.

Suggested structure:
```
src/
  app/                # routes (App Router)
  components/         # reusable UI (ui/ = shadcn primitives, app/ = composed)
  features/           # complaints/, bills/, dues/, notifications/, account/, rules/
  lib/api/            # typed client + Zod schemas (one file per resource)
  lib/hooks/          # useMe, useDashboard, useComplaint, useNotifications, usePush...
  lib/pwa/            # service worker registration + push subscribe
  styles/
```

---

## 3. Auth & session model

- Session = signed cookie `hive_session` (set by the backend on register/login).
- `GET /api/auth/me` → `{ member: SelfMember | null }`. Call once on app load; drive
  routing off it. `null` = logged out.
- **Roles:** `member.role` is `"tenant" | "guest"`.
  - Logged out → public landing / login (or the guest view of `/s/<spot>`).
  - Guest → the **welcome/home** experience (`/me` data).
  - Tenant → the **dashboard**.
- 401 from any call = session invalid/expired → bounce to login.
- Logout: `POST /api/auth/logout` then clear cached queries.

---

## 4. API reference (the contract)

Base path `/api`. All bodies/responses JSON unless noted. **Errors** are always
`{ "detail": string }` with the status code below — surface `detail` in toasts.

### 4.1 Auth
| Method | Path | Auth | Body | Returns | Errors |
|---|---|---|---|---|---|
| GET | `/auth/me` | optional | — | `{ member: SelfMember \| null }` | — |
| POST | `/auth/register` | — | `{ username, password, email?, whatsapp? }` | `{ member: SelfMember }` | 422 (username<3 / password<6 / bad email / bad whatsapp), 409 (taken) |
| POST | `/auth/login` | — | `{ username, password }` | `{ member: SelfMember }` | 401 (wrong creds) |
| POST | `/auth/logout` | — | — | `{ ok: true }` | — |

### 4.2 Home / read
| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/me` | login | `{ member: SelfMember, rulesByCategory: Record<string, Rule[]>, members: Member[], hallOfShame: ShameRow[], gettingHere: GettingHere \| null }` |
| GET | `/dashboard` | **tenant** | `{ pot: number, potCount: number, dues: Due[], recentFines: RecentComplaint[], overturn: Overturn[] }` |
| GET | `/spots/{spot}` | optional | `{ spot, config: {emoji,title,category,shame}, member: SelfMember\|null, isTenant: boolean, rules: Rule[], members: Member[], pot, potCount, hallOfShame: ShameRow[] }` (404 unknown spot) |
| GET | `/public/stats` | — | `{ pot, potCount, hallOfShame: ShameRow[] }` |

`spot` ∈ `front_door | fridge | kitchen | balcony | living_room | bathroom`.

### 4.3 Complaints (the core loop)
| Method | Path | Auth | Body | Returns | Errors |
|---|---|---|---|---|---|
| POST | `/complaints` | login | **multipart**: `accusedId` (int), `ruleId?` (int), `amount?` (int), `note?` (str), `images[]` (≥1 image files) | `{ ok: true, complaintId: number }` | 400 (no image / self-complaint / no rule&no amount / anti-spam), 413 (image too big), 415 (not an image) |
| GET | `/complaints/{id}` | login | — | `ComplaintDetail` | 404 |
| POST | `/complaints/{id}/accept` | login (accused) | — | `{ ok, accepted: boolean }` | 400 |
| POST | `/complaints/{id}/dispute` | login (not accuser) | `{ reason? }` | `{ ok, votingOpened: boolean }` | 403 (accuser), 404 |
| POST | `/complaints/{id}/vote` | login (neutral) | `{ vote: "uphold" \| "void" }` | `{ ok, status, phase, tally: {uphold, void} }` | 400 |
| GET | `/proofs/{id}` | login | — | image bytes (use directly as `<img src>`) | 404 |

> **Anti-spam:** the backend caps complaints/day and blocks a same accused+rule
> duplicate within a window — both come back as **400** with a human `detail`. Show it.

### 4.4 Pay (read-only — never moves money)
| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/pay` | login | `{ unpaid: {id, amount, rule}[], walletQr: string \| null }` |
| POST | `/pay/{fineId}` | login (owner) | `{ paid: true, changed: boolean }` (404 if not yours) |
| POST | `/report` | login | **deprecated → 400** (use `/complaints`). Don't call it. |

### 4.5 Bills (tenant only)
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/bills` | `{ type, total, month, paidBy? }` | `{ ok, billId }` (422 bad type) — `type` ∈ `rent\|house_help\|electricity\|water`, `month` = `"YYYY-MM"` |
| POST | `/bills/{billId}/shares/{memberId}/paid` | — | `{ ok }` (404 no bill) |

> The API doesn't yet expose "list bills / bill shares." Build the **create** +
> **mark-share-paid** flows; for viewing bills, surface dues via `/dashboard`. If you
> need a bills list, note it as a backend ask (don't fake it).

### 4.6 Notifications (in-app feed)
| Method | Path | Returns |
|---|---|---|
| GET | `/notifications?unread=<bool>` | `{ notifications: Notification[], unread: number }` |
| POST | `/notifications/{id}/read` | `{ ok, changed }` |
| POST | `/notifications/read-all` | `{ ok, marked }` |

### 4.7 Account & Web Push
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/account/email` | `{ email? }` (empty clears) | `{ ok, email }` (422 bad) |
| POST | `/account/whatsapp` | `{ whatsapp? }` (E.164, empty clears) | `{ ok, whatsapp }` (422 bad) |
| GET | `/push/public-key` | — | `{ key: string \| null }` (null ⇒ Web Push not configured → hide the toggle) |
| POST | `/push/subscribe` | `{ endpoint, keys: { p256dh, auth } }` | `{ ok }` |
| POST | `/push/unsubscribe` | `{ endpoint }` | `{ ok }` |

### 4.8 Types (define as Zod schemas, infer TS)
```ts
type Role = "tenant" | "guest";
type Member     = { id:number; name:string; username:string|null; role:Role };           // public
type SelfMember = Member & { email:string|null; whatsapp:string|null };                   // your own
type Rule = { id:number; category:string; text:string; amount:number; isFavorite:boolean };
type ShameRow = { name:string; fines:number; total:number };
type Overturn = { name:string; filed:number; upheld:number; overturned:number; overturnRate:number };
// ⚠️ dues uses snake_case (it's the only endpoint that does) — normalize on ingest:
type Due = { member_id:number; name:string; fines:number; bills:number; total:number };
type RecentComplaint = { id:number; accused:string; accuser:string; rule:string|null; amount:number; status:Status; paid:boolean; date:string };
type Proof = { id:number; source:"upload"|"telegram"; contentType:string|null; width:number|null; height:number|null; url:string|null };
type TimelineEvent = { type:EventType; actor:string|null; detail:string|null; ts:string };
type Notification = { id:number; kind:NotificationKind; title:string; body:string|null; fineId:number|null; read:boolean; ts:string };
type GettingHere = { address:string; place?:string; directions?:string; geo?:string; uber?:string; ola?:string; rapido?:string } | { address:string } | null;

type ComplaintDetail = {
  id:number; phase:Phase; status:Status; resolution:Resolution|null;
  accused:Member|null; accuser:Member|null; rule:string|null; amount:number; paid:boolean;
  disputeReason:string|null; coolingDeadline:string|null; voteDeadline:string|null;
  proofs:Proof[]; timeline:TimelineEvent[];
  vote:{ uphold:number; void:number; eligible:number; myVote:"uphold"|"void"|null };
  canAccept:boolean; canDispute:boolean; canVote:boolean;
};
```
Timestamps are ISO-8601 UTC strings like `"2026-06-22T11:30:00Z"`.

---

## 5. Domain enums & the workflow the UI must encode

```ts
type Status = "pending" | "confirmed" | "disputed" | "upheld" | "void";
type Phase  = "raised"  | "registered"| "voting"   | "rejected";       // what to render
type Resolution = "accepted" | "auto_confirmed" | "upheld" | "void";
type EventType = "raised"|"accused_notified"|"accepted"|"disputed"|"voting_started"
               |"members_notified"|"vote_cast"|"vote_finalized"|"auto_confirmed"|"paid";
type NotificationKind = "complaint_raised"|"vote_requested"|"complaint_resolved"|"complaint_registered";
```

**Render off `phase`, not `status`** (the backend collapses status → phase):
- `raised` → awaiting the accused. Show cooling countdown to `coolingDeadline`.
- `voting` → a vote is open. Show countdown to `voteDeadline` + live tally.
- `registered` → it stands (confirmed/upheld). 🎉
- `rejected` → voided/dropped.

**Permission flags are server-truth — obey them, don't recompute:**
- `canAccept` → show **Accept** (only the accused, while raised).
- `canDispute` → show **Deny** (anyone but the accuser, while raised).
- `canVote` → show **Uphold / Void** (neutral members, while voting).
Hide the buttons the flags say you can't use. `vote.myVote` tells you what you already voted.

**Composer rules (enforce client-side, backend re-checks):**
- ≥1 image is **mandatory** — disable submit until a photo exists.
- You can't complain about yourself — exclude `me` from the accused picker.
- A complaint cites a **rule** (preferred) **or** an explicit **amount** (ad-hoc).

---

## 6. Information architecture (routes)

```
/                     public landing — pot ticker, shame teaser, CTA  (tenant→/dashboard, guest→/me)
/login   /register    auth (register captures optional email + whatsapp + push opt-in)
/me                   home / guest welcome — hello, rules menu, shame, "getting here", actions
/dashboard            (tenant) pot, dues, recent feed, overturn leaderboard
/complaints           the feed (filter by phase / mine / about-me)
/complaints/new       camera-first composer
/complaints/[id]      detail — status tracker, proof gallery, vote countdown, contextual actions
/rules                searchable house-rules menu by category
/pay                  wallet QR + your unpaid fines, mark paid
/bills                (tenant) create a bill; dues overview
/shame                full Hall of Shame
/notifications        the feed
/settings             account: email, whatsapp, push toggle, install app, logout
/s/[spot]             NFC spot page (contextual; living_room → dashboard for tenants)
```

Logged-in nav = a **bottom tab bar** (thumb-reachable): **Home · Complaints · ➕ (compose, center FAB) · Pot/Pay · Profile**. A top bar carries the **notification bell** (unread badge) and the pot total.

---

## 7. Screen specs (what each must do)

- **Landing `/`** — big animated **pot ticker** (`/public/stats`), a Hall-of-Shame
  teaser, and "Join your flat" → login/register. Redirect authed users by role.
- **Register/Login** — username + password; register also optionally captures
  **email** + **WhatsApp** (so notifications reach them) and prompts to **enable push**.
  Map 422→inline field errors, 409→"username taken", 401→"wrong login."
- **Home `/me`** — personalized hello; **rules as a menu** grouped by category
  (emoji + amount, like a food menu); **Hall of Shame**; **"Getting here"** card
  (render `gettingHere`: Open in Maps `geo:`/`directions`, copy address, Uber/Ola/Rapido;
  hide if null); primary actions **Report · Pay · Behave 😇**.
- **Dashboard `/dashboard`** (tenant) — **Pot** hero (₹ + count), **Dues** table
  (biggest debtor first; `Due.member_id/name/fines/bills/total`), **Recent complaints**
  feed (`recentFines`), **Overturn leaderboard** (`overturn`, the "biggest false-reporter 🏆").
- **Composer `/complaints/new`** — see §8 CameraComposer. Camera-first, 3 quick steps.
- **Complaint detail `/complaints/[id]`** — proof **gallery/lightbox** (use `proof.url`),
  a **status tracker / timeline** (from `phase` + `timeline[]`), the **vote panel**
  (countdown to `voteDeadline`, live `vote` tally, your `myVote`), and **contextual
  action buttons** driven by `canAccept/canDispute/canVote`. For `raised`, show the
  cooling countdown. Confetti on reaching `registered`.
- **Complaints feed `/complaints`** — filter chips (All / About me / By me / Voting now);
  cards show accused, rule, amount, phase chip, and a countdown if live.
- **Rules `/rules`** — search + category tabs + favorites; tap a rule to start a complaint.
- **Pay `/pay`** — `walletQr` (UPI QR; if null, show the message that pay is manual),
  list `unpaid` fines, **"I paid"** marks each (`POST /pay/{id}`) — copy makes clear
  it's a claim, not a transfer.
- **Bills `/bills`** (tenant) — **create bill** sheet (type, total, month); since the
  API has no bills-list yet, show dues from `/dashboard` and the create flow.
- **Shame `/shame`** — full leaderboard with rank, count, total; medals for top 3.
- **Notifications `/notifications`** — feed grouped by day; tap → deep-link to the
  complaint (`fineId`); mark read / read-all; unread styling.
- **Settings `/settings`** — set/clear email + WhatsApp; **push toggle** (hidden if
  `/push/public-key` is null); **Install app** (PWA prompt); logout.
- **NFC `/s/[spot]`** — public, role-aware (`/spots/{spot}`): anon → rules +
  "log in to report/pay"; member → report form pre-filtered to `config.category`;
  tenant on `living_room` (`config.shame`/control room) → link to dashboard.

---

## 8. Components & modules (build these)

- **AppShell** — bottom tab bar + center compose FAB + top bar (pot + 🔔 bell).
- **PotTicker** — animated counting ₹ total.
- **ComplaintCard** — accused, rule, amount, **PhaseChip**, optional countdown.
- **PhaseChip** — color-coded badge per `phase` (raised=amber, voting=violet, registered=green, rejected=gray).
- **StatusTracker / Timeline** — stepper rendered from `timeline[]` events.
- **VoteCountdown** — live mm:ss/“2h left” to `voteDeadline`/`coolingDeadline`; on
  expiry, refetch the complaint (server sweep finalizes within ~5 min).
- **VotePanel** — uphold/void buttons (respect `canVote`/`myVote`) + tally bars.
- **CameraComposer** — `<input type="file" accept="image/*" capture="environment">`
  first; preview thumbnails; then **MemberPicker** (excludes self) → **RulePicker** →
  review (note optional) → submit as multipart. Disable submit with 0 images.
- **MemberPicker** — avatar grid of active members (from `/me` `members`).
- **RulePicker** — favorites first + category browse + search; shows amount.
- **ProofGallery / Lightbox** — thumbnails → fullscreen swipeable viewer.
- **DuesList**, **ShameLeaderboard**, **OverturnLeaderboard**, **RulesMenu**.
- **NotificationBell** + **NotificationList** + **NotificationItem**.
- **GettingHereCard**, **WalletQR**, **BillCreateForm**.
- **Toast system**, **ConfettiBurst**, **Skeletons**, **EmptyState**, **PWAInstallPrompt**, **PushPermissionPrompt**.

---

## 9. Popups / sheets / modals (gen-z = bottom sheets)

Prefer **bottom sheets** on mobile (Base UI / shadcn Drawer), modals on desktop:
- **Decision sheet** — Accept / Deny on the accused's complaint (with proof + reason field for deny).
- **Vote sheet** — Uphold / Void, showing the proof, rule, amount, accuser, and the denial reason.
- **Compose sheets** — camera capture, member picker, rule picker (the §8 composer steps as stacked sheets).
- **Confirm pay sheet** — "Mark ₹X paid into the jar?" (claim, not transfer).
- **Create bill sheet** (tenant).
- **Push permission prompt** — soft pre-prompt → browser permission → subscribe.
- **PWA install prompt** — "Add Hive to your home screen."
- **Image lightbox**.
- **Result/confetti modal** — on a complaint reaching `registered`.
- **Inline warnings** (toasts) for anti-spam 400s, 413/415 image errors, 409 username taken.

---

## 10. Notifications integration

The backend fans every event to **in-app + Web Push + email + WhatsApp**. The
frontend implements two of these:

1. **In-app feed** — `GET /notifications`. Poll on an interval + **refetch on window
   focus** + after any mutation; show the unread count on the bell; deep-link each to
   `/complaints/{fineId}`.
2. **Web Push (PWA)** —
   - On opt-in: `GET /push/public-key` (if `null`, push is off → hide the toggle).
   - Register the **service worker**, `pushManager.subscribe({ userVisibleOnly:true,
     applicationServerKey: <vapidKey> })`, then `POST /push/subscribe` with
     `{ endpoint, keys:{ p256dh, auth } }` (from `subscription.toJSON()`).
   - SW `push` handler shows the notification; `notificationclick` opens the `url`
     in the payload (`{ title, body, url, tag }`) — deep-link to the complaint.
   - On disable: `POST /push/unsubscribe { endpoint }`.
   - **iOS caveat:** Web Push only works for an **installed PWA** (Add to Home Screen,
     iOS 16.4+) — so push the install prompt, and rely on **email/WhatsApp** for users
     who don't install. Let them set those in Settings (`/account/email`, `/account/whatsapp`).

Email & WhatsApp are delivered server-side; the frontend only **captures the
contact details** and explains the value ("get pinged on WhatsApp when you're accused").

---

## 11. Design system — the gen-z language (you decide the specifics)

Make it feel like a Gen-Z social app, not enterprise software. Direction (own the details):
- **Dark-mode-first**, high-contrast, one **vibrant gradient** accent + playful secondary colors; big **rounded-2xl** cards; generous spacing; chunky tap targets.
- **Emoji-forward** and meme-y microcopy (🚨 🫙 ⚖️ 🏆 😇). The pot is "the jar." Fines are "receipts."
- **Motion everywhere (tasteful):** spring transitions, animated pot counter, **confetti** on "registered," haptic-style button presses, sheet drag-to-dismiss, list stagger, skeleton shimmer, **pull-to-refresh**.
- **Social mechanics:** Hall of Shame leaderboard with medals, "biggest false-reporter" badge, avatars (generate from name/initials), streaks ("days without a fine"), vote tally bars that fill live.
- **Receipt / sticker aesthetic** for complaint cards; **countdown timers** front-and-center for live votes.
- **Always** respect `prefers-reduced-motion`, keep contrast accessible, and keep it fast (lazy images, thumbnails via `proof.url`, optimistic UI).

---

## 12. State, data & optimistic UX

- **TanStack Query** per resource; query keys: `["me"]`, `["dashboard"]`,
  `["complaint", id]`, `["notifications"]`, `["pay"]`, `["publicStats"]`.
- **Optimistic mutations** for accept / deny / vote / mark-paid; on success
  **invalidate** the complaint + dashboard + notifications + pay.
- **No websockets exist** → poll `/notifications` (e.g. 30–60s) + refetch on focus;
  for a live vote, also refetch around `voteDeadline`.
- A single typed **API client** (`lib/api`) that: sends credentials, parses with Zod,
  and throws a normalized `ApiError { status, detail }`. A 401 handler routes to login.

---

## 13. Errors, empty & loading states (don't skip these)

- Map status → UX: **401**→login; **403**→"not allowed" (you filed it / tenants only);
  **404**→not-found screen; **409**→"username taken"; **413/415**→image error in the
  composer; **422**→inline field validation; **400**→toast the `detail` (covers
  anti-spam + state errors). Everything else → generic retry toast.
- **Empty states** with personality for: no complaints, empty pot, no dues, no
  notifications, empty shame board.
- **Skeletons** for every list/detail while loading; never a blank flash.

---

## 14. PWA requirements

- `manifest.webmanifest` (name, icons, theme, `display: standalone`), installable.
- Service worker: Web Push (`push` + `notificationclick`) and basic offline shell
  (cache the app shell; the API stays network-first).
- An in-app **Install** affordance (and the iOS "Add to Home Screen" hint).

---

## 15. Edge cases & gotchas checklist

- [ ] Proof mandatory — submit disabled until ≥1 image; camera-first.
- [ ] Exclude self from the accused picker; obey `canAccept/canDispute/canVote`.
- [ ] Render off `phase`; show the right countdown (`coolingDeadline` vs `voteDeadline`).
- [ ] Vote tally + `myVote` reflect server truth; refetch on/after deadline.
- [ ] `dues` is **snake_case** (`member_id`) — the only endpoint that is; normalize it.
- [ ] `gettingHere` / `walletQr` / push `key` can be **null** → hide those UIs gracefully.
- [ ] Tenant-only: dashboard + bills (guests get 403 — don't show the entrances).
- [ ] `/report` is dead (400) — never call it; always use `/complaints` multipart.
- [ ] iOS push needs an installed PWA → lean on email/WhatsApp fallback + install prompt.
- [ ] Proof images: `proof.url` (only for `source:"upload"`); `source:"telegram"` has `url:null` (legacy) → show a placeholder.
- [ ] Always send cookies; treat 401 as logged-out globally.

---

## 16. Build order (milestones)

1. **Foundation** — Next App Router + Tailwind + shadcn + TanStack Query + Zod; the
   typed API client; auth (`/auth/*`), `useMe`, role-based routing, AppShell + bottom nav.
2. **Read surfaces** — Landing, Home `/me` (rules menu, shame, getting-here),
   Dashboard, Rules, Shame. Skeletons + empty states.
3. **The core loop** — Camera composer → `POST /complaints`; complaint detail with
   timeline + proof gallery; **accept / deny / vote** with optimistic UX + confetti;
   complaints feed.
4. **Money** — Pay screen (QR + mark paid); Bills create (tenant).
5. **Notifications + PWA** — in-app feed + bell; service worker + Web Push subscribe;
   Settings (email/whatsapp/push/install); deep-links.
6. **Polish** — motion, haptics, gen-z design pass, accessibility, reduced-motion,
   performance (image lazy-load), NFC `/s/[spot]` pages.

---

## 17. Definition of done

- Every endpoint in §4 consumed through a Zod-validated, credentialed client.
- The full complaint loop works end-to-end on a phone: photo → file → accused
  accepts **or** denies → vote → registered/rejected, with live countdowns and
  correct permission-gated buttons.
- All loading / empty / error states handled; tenant/guest gating correct.
- Installable PWA with working Web Push (where configured) + email/WhatsApp capture.
- It looks and feels like something a 23-year-old would actually want to open. 🐝

> Reminder: when in doubt, **read `../hive-api`** (`app/api/routes`, `app/schemas`,
> `app/domain/enums.py`, `app/services/complaints.py`, `app/services/proposals.py`) and match the code exactly.

---

## Appendix — Rule Proposals (v5)

The rule book is amended by a **community vote**. Anyone proposes a new/modify/delete
rule; **tenants** vote (one each, yes/no/abstain, changeable until the deadline); at
close, configurable quorum+majority decide pass/reject; a passed proposal auto-merges
into the rule book with immutable version history.

**Enums:** `type` = `new_rule|modify_rule|delete_rule`; `status` = `draft|pending_review|
voting|passed|rejected|expired|cancelled`; `phase` (render off this) = `draft|review|
voting|passed|rejected|cancelled`; vote `choice` = `yes|no|abstain`.

**API (all under `/api`, session-cookie auth):**
| Method | Path | Notes |
|---|---|---|
| POST | `/proposals` | `{type, title, body?, targetRuleId?, proposedCategory?, proposedText?, proposedAmount?, submit?}` → `{proposalId}` |
| GET | `/proposals?status=` | list (summaries + tally) |
| GET | `/proposals/{id}` | full detail: proposal + `proposer` + `vote{yes,no,abstain,eligible,myVote}` + `comments[]` + `timeline[]` + `canVote/canEdit/canAdmin` |
| PATCH | `/proposals/{id}` | edit a draft; send `expectedVersion` (optimistic lock → 409 on stale) |
| POST | `/proposals/{id}/submit` | draft → voting (or pending_review) |
| POST | `/proposals/{id}/vote` | `{vote}` (tenants only; 403 for guests; 400 after deadline) |
| GET | `/proposals/{id}/votes` · `/timeline` | tally + voters · event log |
| GET/POST | `/proposals/{id}/comments` | list / add `{body, parentId?}` |
| PATCH/DELETE | `/proposals/{id}/comments/{cid}` | edit (author) / soft-delete (author or admin) |
| POST | `/proposals/{id}/cancel` | proposer or admin |
| POST | `/proposals/{id}/{approve\|reject\|extend\|freeze\|force-merge}` | **admin (tenant)**; `extend{hours}`, `freeze{frozen}` |
| GET | `/rulebook` | active rules (the official book) |
| GET | `/rulebook/{ruleId}/versions` | immutable version history |
| POST | `/rulebook/{ruleId}/rollback/{versionId}` | **admin**; restore a prior version |

**Screens to build:** a **Proposals** tab (list with phase chips + live vote bars +
countdown), a **proposal detail** (rationale, vote Yes/No/Abstain gated by `canVote`,
tally + countdown, timeline, comments), a **"Propose a rule"** composer (type picker +
rule fields + rationale), a **Rule Book** view with per-rule **version history + rollback**
(admin), and admin controls on the detail when `canAdmin`. New notification kinds:
`proposal_voting`, `proposal_comment`, `proposal_resolved`, `rule_published`, `proposal_review`
(each carries `proposalId` → deep-link to `/proposals/{id}`).

> Interactive API docs are auto-served by FastAPI at `/docs` (Swagger) and `/openapi.json`.

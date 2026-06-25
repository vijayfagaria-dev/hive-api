# Hive — v1 — API Surface

> **Plan folder:** `plans/v1/`
> **Status:** DRAFT
> **Related files:** [overview](overview.md) | [requirements](requirements.md) | [data-dictionary](data-dictionary.md) | [business-rules](business-rules.md) | [shared-definitions](shared-definitions.md) | [task-summary](task-summary.md)

Two faces, one FastAPI app. The bot is the fast lane for input; the web side is read-only overview.

## 1. Web routes (FastAPI)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness probe → `{"status":"ok"}`. |
| GET | `/` | none (v1) | Read-only HTML dashboard: pot, dues table, recent fines, overturn leaderboard. |
| POST | `/telegram/webhook/{secret}` | secret path + `X-Telegram-Bot-Api-Secret-Token` header (BR-061) | Telegram update intake → fed to the aiogram dispatcher. Only mounted when `bot_enabled`. |

The dashboard is intentionally unauthenticated in v1 (OQ-2); it exposes nothing actionable and no secrets. A Mini App / login is a later decision.

## 2. Bot surface (aiogram 3)

Tap-driven, not command-memorizing. Commands bootstrap a flow; inline keyboards do the rest.

### Onboarding model (v1 refinement of BR-010)
There's no separate admin channel, so the flat bootstraps itself:
- The **first ever** `/start` on an empty DB creates the **founding tenant** and links them.
- After that, an active tenant adds a flatmate by name with **`/addtenant <name>`** (creates an unlinked record; duplicate active names are rejected).
- The new person `/start`s and taps **“That's me — <name>”** to link their Telegram account.

This keeps BR-010 intact: nobody silently becomes a tenant — they either bootstrap an empty flat or claim a record a tenant deliberately created.

### Commands
| Command | Does |
|---|---|
| `/start` | Founder bootstrap (empty flat) · greet if linked · offer claim buttons if there are unlinked tenants · else nudge to be added (BR-010). |
| `/addtenant <name>` | An active tenant adds a flatmate (unlinked until they claim). Rejects a duplicate active name. |
| `/pot` | Current pot total + confirmed-fine count (BR-035). |
| `/dues` | The caller's unpaid fines + bill shares, with pay buttons (BR-050). `/dues all` → the whole-flat table. |
| `/fine [text]` | Fine flow: pick a rule (favorites · browse · `text` search) → pick the accused → `pending` fine + card (BR-020/031/034). |
| `/bill <type> <amount> [YYYY-MM]` | Arg-driven: records the bill and snapshots one `bill_shares` row per active tenant (BR-003). Defaults to the current month. |
| `/rules` | Browse rules: favorites overview + category drill-down. |

### Callback queries (inline buttons)
Typed via aiogram `CallbackData` (prefixes in parens). Flows are stateless — ids ride in the payload.
| Callback (prefix) | From | Action |
|---|---|---|
| `claim` `Claim(member_id)` | `/start` claim list | Link the caller's Telegram id to that tenant record. |
| `fine:cats` (plain) | `/fine` favorites | Open the category list. |
| `fcat` `FineCat(category)` | `/fine` browse | List that category's rules. |
| `frule` `FineRule(rule_id)` | `/fine` rule list | Select the rule; show the accused picker (excludes the reporter, BR-034). |
| `fwho` `FineWho(rule_id, member_id)` | accused picker | Create the `pending` fine + post the card with a Dispute button. |
| `fdis` `FineDispute(fine_id)` | the fine card | One-tap dispute while pending → `status='disputed'` (BR-033). |
| `fpay` `FinePay(fine_id)` | `/dues` | Mark the caller's own fine paid (BR-036); re-render dues. |
| `dshr` `DuesShare(bill_id)` | `/dues` | Mark the **caller's own** share paid (BR-043); re-render the private dues view. |
| `bshr` `BillShare(bill_id, member_id)` | bill card | Mark a named share paid (BR-043); re-render the shared bill card. |
| `rcat` `RulesCat(category)` | `/rules` | Show that category's rules (read-only). |

## 3. Background job
| Job | Cadence | Action |
|---|---|---|
| Pending-fine sweep | every `SWEEP_INTERVAL_SECONDS` (default 300s) + once on startup | Promote overdue, undisputed `pending` fines → `confirmed` (BR-032). |

## 4. Not in v1
No guest routes, no NFC `/s/<spot>` routes (v2). No voting endpoints, no money-ingest webhook, no settle endpoint (v3). No write/management endpoints on the web side — all mutation goes through the bot.

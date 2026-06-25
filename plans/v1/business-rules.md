# Hive — v1 — Business Rules

> **Plan folder:** `plans/v1/`
> **Status:** DRAFT
> **Related files:** [overview](overview.md) | [requirements](requirements.md) | [data-dictionary](data-dictionary.md) | [api-surface](api-surface.md) | [shared-definitions](shared-definitions.md) | [task-summary](task-summary.md)

Rules are testable assertions. Each cites its `_Source:_` REQ and `_Enforced by:_` mechanism.

## The hard rule — ledger, not custody

- **BR-000:** The app never holds or moves money. No code path takes custody of funds or initiates a transfer; it only records claims and computes totals. The physical jar is the throwaway wallet.
  _Source:_ DESIGN "the hard rule" [Explicit] _Enforced by:_ absence of any payment/transfer integration; `paid` flags are operator-set records, not money movements.

## Members & roles

- **BR-001:** A tenant (`role='tenant'`, `is_active=1`) is in bill splits, can fine anyone, can pay, can manage rules. Permissions are flat — no admin tier. Fining is an *active*-flatmate action: both accused and accuser must be active.
  _Source:_ REQ-M-001, REQ-M-003 [Explicit] _Enforced by:_ no role checks beyond tenant/guest; `fines.create_fine` rejects an inactive accused or accuser; the bot pickers only offer active tenants.
- **BR-002:** The `guest` role, `host_id`, and `left_on` exist in the schema from v1 but carry **no v1 behaviour**. They are forward-compat only.
  _Source:_ REQ-M-002 [Explicit] _Enforced by:_ schema columns present; no v1 code reads/writes guest behaviour.
- **BR-010:** A member's `telegram_id` is set the first time they `/start`; lookups are by `telegram_id`. A `/start` from an unknown Telegram user does not auto-create a tenant (tenants are added deliberately).
  _Source:_ REQ-M-004 [Inferred] _Enforced by:_ `get_member_by_telegram` + explicit `add_member`/`link_telegram`.

## The snapshot (load-bearing)

- **BR-003:** On bill creation, exactly one `bill_shares` row is written per **currently-active tenant**, with the split frozen. Splits are **never** computed live (`total ÷ count`) anywhere. Adding a later tenant must not change any past bill's shares.
  _Source:_ REQ-B-002 [Explicit] _Enforced by:_ `queries.create_bill_with_shares` snapshots at creation; no live-split code exists; UNIQUE(`bill_id`,`member_id`).
- **BR-042:** Integer-rupee shares sum to **exactly** `bills.total`; the division remainder is assigned to the first tenant (no rupee lost to rounding).
  _Source:_ REQ-B-004 [Inferred] _Enforced by:_ `divmod(total, n)` with remainder added to index 0 in `create_bill_with_shares`.
- **BR-040:** A bill's `type` is one of `rent`, `house_help`, `electricity`, `water`. No other expense types.
  _Source:_ REQ-B-001 [Explicit] _Enforced by:_ `bills.type` CHECK constraint.
- **BR-041:** Only active **tenants** are in a split. Guests are never snapshotted into `bill_shares`.
  _Source:_ REQ-B-003 [Explicit] _Enforced by:_ `create_bill_with_shares` iterates `list_active_tenants` (role='tenant').
- **BR-043:** A bill share is marked paid per `(bill_id, member_id)`.
  _Source:_ REQ-B-005 [Inferred] _Enforced by:_ `queries.mark_share_paid`.

## Fines — claim, not verdict

- **BR-030:** A fine moves only through `pending → confirmed | disputed | void | upheld`. No other transitions; `status` is the single source of truth for whether a fine counts.
  _Source:_ REQ-F-001 [Explicit] _Enforced by:_ `fines.status` CHECK; transitions only via the `fines.py` service.
- **BR-031:** A new fine is created `pending` with `confirm_deadline = now + COOLING_HOURS`.
  _Source:_ REQ-F-002 [Explicit] _Enforced by:_ `fines.create_fine` + `deadline_iso`.
- **BR-032:** The sweep promotes a fine to `confirmed` **iff** `status='pending'` AND `now > confirm_deadline` AND it is not disputed. Disputed fines are never auto-confirmed.
  _Source:_ REQ-F-002 [Explicit] _Enforced by:_ `fines.sweep_due` UPDATE guarded by `status='pending' AND confirm_deadline < now`.
- **BR-033:** Disputing is one tap and always available while pending. A disputed fine parks (`status='disputed'`) for the humans; v1 has no auto-resolution and no penalty for disputing.
  _Source:_ REQ-F-003 [Explicit] _Enforced by:_ a single Dispute callback → `queries.dispute_fine`; no cost path.
- **BR-034:** Every fine records `added_by` (accuser) and `member_id` (accused); they may not be the same person.
  _Source:_ REQ-F-004 [Explicit] _Enforced by:_ `create_fine` requires both; the bot's accused picker excludes the reporter.
- **BR-035:** Pot total = `SUM(amount)` over fines with `status IN ('confirmed','upheld')`. Nothing is applied to rent in v1 (month-end settle is v3).
  _Source:_ REQ-F-005 [Explicit] _Enforced by:_ `queries.pot_total` over `OWED_STATUSES`.
- **BR-036:** `paid` is independent of `status` — a confirmed fine can be unpaid; marking paid never changes `status`. Only an *owed* fine (`confirmed`/`upheld`) may be marked paid, so the pot and dues can't desync (a prematurely-paid pending fine would later sweep into the pot yet vanish from dues).
  _Source:_ REQ-F-006 [Explicit] _Enforced by:_ separate `paid` column; `fines.mark_paid` touches only `paid` (never `status`), rejects non-`OWED_STATUSES` fines, and returns whether it actually flipped (idempotent on double-tap).
- **BR-037:** `amount` is snapshotted onto the fine at creation from the rule's `fine_amount`; later edits to the rule don't rewrite existing fines. (Same snapshot discipline as bills.)
  _Source:_ REQ-F-001 [Inferred] _Enforced by:_ `create_fine` copies the amount into `fines.amount`.

## Dues, pot & the visible stat

- **BR-050:** A member's dues = unpaid `confirmed`/`upheld` fines + unpaid `bill_shares`. `pending`/`disputed`/`void` fines are **not** dues.
  _Source:_ REQ-D-001 [Explicit] _Enforced by:_ `queries.member_dues` filters `paid=0 AND status IN OWED_STATUSES` + unpaid shares.
- **BR-051:** The overturn stat (filed / upheld / overturned + %) is computed per active member and shown on the dashboard. It is read-only in v1 (no loser-pays, no auto downgrade).
  _Source:_ REQ-D-003 [Explicit] _Enforced by:_ `queries.overturn_stats`; rendered on the dashboard.

## Platform & safety

- **BR-021:** Each fine bumps the rule's `use_count` so the most-fined rules bubble up in their list.
  _Source:_ REQ-R-003 [Explicit] _Enforced by:_ `bump_rule_use` called on fine creation.
- **BR-020:** Rule selection never shows all rules at once: favorites first, then category browse, then text search.
  _Source:_ REQ-R-002 [Explicit] _Enforced by:_ `list_favorite_rules` / `list_categories` / `search_rules` + the bot keyboards.
- **BR-060:** The app boots and serves health + dashboard with **no** `TELEGRAM_BOT_TOKEN`; the bot is simply disabled.
  _Source:_ REQ-P-003 [Inferred] _Enforced by:_ `settings.bot_enabled` guard in `main.py` lifespan + webhook route.
- **BR-061:** The webhook only accepts requests on the secret path AND carrying Telegram's matching secret-token header; others get 403.
  _Source:_ REQ-P-004 [Inferred] _Enforced by:_ unguessable `webhook_path` + `X-Telegram-Bot-Api-Secret-Token` check.
- **BR-062:** Secrets come only from `.env` (gitignored); none are committed.
  _Source:_ REQ-P-002 [Explicit] _Enforced by:_ `config.py` reads env; `.env` in `.gitignore`; `.env.example` holds blanks.

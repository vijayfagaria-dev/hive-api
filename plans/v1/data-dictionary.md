# Hive — v1 — Data Dictionary

> **Plan folder:** `plans/v1/`
> **Status:** DRAFT — mirrors `app/schema.sql` and DESIGN.md "Data model". Keep all three in sync.
> **Related files:** [overview](overview.md) | [requirements](requirements.md) | [business-rules](business-rules.md) | [api-surface](api-surface.md) | [shared-definitions](shared-definitions.md) | [task-summary](task-summary.md)

One SQLite file (`DATABASE_PATH`, default `hive.db`). WAL mode, foreign keys ON.
Money = integer rupees. Timestamps = ISO-8601 UTC TEXT. Booleans = INTEGER 0/1.

## 1. SQL Tables

### `members` — people in the flat
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | Display name. |
| `telegram_id` | INTEGER UNIQUE | Nullable until they `/start`; linked then. |
| `role` | TEXT NOT NULL `'tenant'` | CHECK in (`tenant`,`guest`). v1 creates tenants only. |
| `is_active` | INTEGER NOT NULL 1 | In the house right now? Drives splits & dues. |
| `joined_on` | TEXT NOT NULL | ISO date/time. |
| `left_on` | TEXT | Set when they leave (v3 leave-flow; column exists now). |
| `host_id` | INTEGER FK→members | Which tenant invited a guest; NULL for tenants. CHECK: non-NULL only for guests. |

### `rules` — the 100-rule list
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `category` | TEXT NOT NULL | Drives category browse. |
| `text` | TEXT NOT NULL | The rule, written menu-style. |
| `fine_amount` | INTEGER NOT NULL ≥0 | Default fine in rupees. |
| `is_favorite` | INTEGER NOT NULL 0 | ⭐ → quick button. |
| `use_count` | INTEGER NOT NULL 0 | Self-tunes ordering; bumped on each fine. |
| `severity_tier` | TEXT NOT NULL `'low'` | CHECK in (`low`,`high`). Exists for v3 tuning; no v1 branching (OQ-1). |
| `auto_confirm` | INTEGER NOT NULL 1 | Forward-compat flag; v1 cooling window is uniform. |

### `fines` — reported fines (claims)
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `member_id` | INTEGER NOT NULL FK→members | The **accused**. |
| `rule_id` | INTEGER FK→rules | Nullable (ad-hoc fine with no rule). |
| `amount` | INTEGER NOT NULL ≥0 | Snapshotted from the rule at fine time (rule edits don't rewrite old fines). |
| `ts` | TEXT NOT NULL | When reported (ISO UTC). |
| `added_by` | INTEGER NOT NULL FK→members | The **accuser** (accountability). |
| `status` | TEXT NOT NULL `'pending'` | CHECK in (`pending`,`confirmed`,`disputed`,`void`,`upheld`). |
| `paid` | INTEGER NOT NULL 0 | Independent of `status`. |
| `confirm_deadline` | TEXT | `ts + COOLING_HOURS`; the sweep promotes after this. |
| `dispute_reason` | TEXT | Optional note when disputed. |

### `fine_votes` — disputed-fine votes (**v3; table only in v1**)
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `fine_id` | INTEGER NOT NULL FK→fines | |
| `voter_id` | INTEGER NOT NULL FK→members | |
| `vote` | TEXT NOT NULL | CHECK in (`uphold`,`void`). |
| — | UNIQUE(`fine_id`,`voter_id`) | One vote per member per fine. |

Present so schema ↔ DESIGN.md stay in sync. No v1 code writes here.

### `bills` — the four recurring bills
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `type` | TEXT NOT NULL | CHECK in (`rent`,`house_help`,`electricity`,`water`). Closed set by design. |
| `total` | INTEGER NOT NULL ≥0 | Rupees. |
| `month` | TEXT NOT NULL | `'YYYY-MM'`. |
| `paid_by` | INTEGER FK→members | Who fronted it (nullable). |
| `ts` | TEXT NOT NULL | Creation time. |

### `bill_shares` — POINT-IN-TIME SNAPSHOT
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_id` | INTEGER NOT NULL FK→bills | |
| `member_id` | INTEGER NOT NULL FK→members | An active tenant **at creation time**. |
| `share_amount` | INTEGER NOT NULL ≥0 | Frozen split. Shares sum to `bills.total` exactly. |
| `paid` | INTEGER NOT NULL 0 | Per-share paid flag. |
| — | UNIQUE(`bill_id`,`member_id`) | One share per member per bill. |

**This table is load-bearing (BR-003).** One row per active tenant is written at bill creation and never recomputed.

## 2. Indexes
`idx_fines_member`, `idx_fines_addedby`, `idx_fines_status`, `idx_rules_category`, `idx_shares_bill`, `idx_shares_member`.

## 3. Derived values (not stored)
| Value | Definition | Where |
|---|---|---|
| **Pot total** | `SUM(fines.amount)` where `status IN ('confirmed','upheld')` | `queries.pot_total` |
| **Member dues** | unpaid owed fines + unpaid bill shares for a member | `queries.member_dues` |
| **Overturn stat** | per-member filed / upheld / overturned + % | `queries.overturn_stats` |

## 4. Forward-compat columns (exist in v1, used later)
`members.left_on`, `members.host_id`, `rules.severity_tier`, `rules.auto_confirm`, the whole `fine_votes` table, fine statuses `void`/`upheld`. They are in the schema now so v2/v3 never has to retrofit — per DESIGN's "the one thing you can't cleanly retrofit."

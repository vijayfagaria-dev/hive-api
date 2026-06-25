-- Hive — schema (v1).
-- Mirrors DESIGN.md "Data model". Keep this file and that doc in sync.
--
-- Conventions:
--   * money is stored as INTEGER rupees (the pot is small; paise are noise).
--   * booleans are INTEGER 0/1.
--   * timestamps/dates are TEXT ISO-8601 in UTC (e.g. '2026-06-22T11:30:00Z').

PRAGMA foreign_keys = ON;

-- People in the flat. v1 only creates tenants; the guest role lands in v2 but
-- the columns exist now so we never have to retrofit them.
CREATE TABLE IF NOT EXISTS members (
  id           INTEGER PRIMARY KEY,
  name         TEXT    NOT NULL,
  telegram_id  INTEGER UNIQUE,                 -- nullable until they /start
  username     TEXT,                           -- v2 web login; unique via idx_members_username (lower)
  password_hash TEXT,                          -- v2 bcrypt hash; NULL for bot-only members
  role         TEXT    NOT NULL DEFAULT 'tenant'
                       CHECK (role IN ('tenant', 'guest')),
  is_active    INTEGER NOT NULL DEFAULT 1,     -- in the house right now?
  joined_on    TEXT    NOT NULL,
  left_on      TEXT,
  host_id      INTEGER REFERENCES members(id), -- which tenant invited a guest
  CHECK (role = 'guest' OR host_id IS NULL)    -- only guests have a host
);

-- The 100-rule list. Selection (favorites/categories/search) is what scales,
-- not storage. use_count self-tunes which rules bubble up.
CREATE TABLE IF NOT EXISTS rules (
  id            INTEGER PRIMARY KEY,
  category      TEXT    NOT NULL,
  text          TEXT    NOT NULL,
  fine_amount   INTEGER NOT NULL CHECK (fine_amount >= 0),
  is_favorite   INTEGER NOT NULL DEFAULT 0,    -- surfaces as a quick button
  use_count     INTEGER NOT NULL DEFAULT 0,    -- most-fined rules bubble up
  severity_tier TEXT    NOT NULL DEFAULT 'low'
                        CHECK (severity_tier IN ('low', 'high')),
  auto_confirm  INTEGER NOT NULL DEFAULT 1     -- low fines lazy-confirm
);

-- A reported fine is a CLAIM, not a verdict. Respect the status workflow.
-- v1 implements Layer 1 only: pending -> confirmed (cooling window) | disputed.
-- void/upheld arrive with voting in v3, but are valid statuses now.
CREATE TABLE IF NOT EXISTS fines (
  id               INTEGER PRIMARY KEY,
  member_id        INTEGER NOT NULL REFERENCES members(id),  -- the accused
  rule_id          INTEGER REFERENCES rules(id),
  amount           INTEGER NOT NULL CHECK (amount >= 0),
  ts               TEXT    NOT NULL,
  added_by         INTEGER NOT NULL REFERENCES members(id),  -- the accuser
  status           TEXT    NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'confirmed',
                                             'disputed', 'void', 'upheld')),
  paid             INTEGER NOT NULL DEFAULT 0,
  confirm_deadline TEXT,                                      -- pending auto-confirms after this
  dispute_reason   TEXT
);

-- Only for disputed fines (voting is v3). Table exists now to keep schema and
-- DESIGN.md in sync.
CREATE TABLE IF NOT EXISTS fine_votes (
  id       INTEGER PRIMARY KEY,
  fine_id  INTEGER NOT NULL REFERENCES fines(id),
  voter_id INTEGER NOT NULL REFERENCES members(id),
  vote     TEXT    NOT NULL CHECK (vote IN ('uphold', 'void')),
  UNIQUE (fine_id, voter_id)
);

-- The four recurring bills. type is closed by design (non-goal: arbitrary splits).
CREATE TABLE IF NOT EXISTS bills (
  id      INTEGER PRIMARY KEY,
  type    TEXT    NOT NULL CHECK (type IN ('rent', 'house_help',
                                           'electricity', 'water')),
  total   INTEGER NOT NULL CHECK (total >= 0),
  month   TEXT    NOT NULL,                  -- 'YYYY-MM'
  paid_by INTEGER REFERENCES members(id),    -- who fronted it
  ts      TEXT    NOT NULL
);

-- POINT-IN-TIME SNAPSHOT. One row per active tenant at bill-creation time.
-- Never compute splits live (see DESIGN.md "splits must be point-in-time").
-- June stays ÷4 forever even after July splits ÷6.
CREATE TABLE IF NOT EXISTS bill_shares (
  id           INTEGER PRIMARY KEY,
  bill_id      INTEGER NOT NULL REFERENCES bills(id),
  member_id    INTEGER NOT NULL REFERENCES members(id),
  share_amount INTEGER NOT NULL CHECK (share_amount >= 0),
  paid         INTEGER NOT NULL DEFAULT 0,
  UNIQUE (bill_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_fines_member   ON fines(member_id);
CREATE INDEX IF NOT EXISTS idx_fines_addedby  ON fines(added_by);
CREATE INDEX IF NOT EXISTS idx_fines_status   ON fines(status);
CREATE INDEX IF NOT EXISTS idx_rules_category ON rules(category);
CREATE INDEX IF NOT EXISTS idx_shares_bill    ON bill_shares(bill_id);
CREATE INDEX IF NOT EXISTS idx_shares_member  ON bill_shares(member_id);

# Hive — v2 — Requirements

> **Plan folder:** `plans/v2/`
> **Status:** DRAFT — simple-accounts model + Getting here.
> **Related:** [overview](overview.md) · [data-dictionary](data-dictionary.md) · [business-rules](business-rules.md) · [api-surface](api-surface.md) · [shared-definitions](shared-definitions.md) · [task-summary](task-summary.md)

Tagged `[Explicit]` (DESIGN.md), `[Inferred]` (gap-fill), or `[User]` (added directly by the owner). Each maps to a business rule / surface.

## Accounts & roles

- **REQ-A-001** `[User]` Anyone can **self-register** with a **username + password**. Registration creates an active member whose role defaults to **guest**. → BR-A01, BR-A02
- **REQ-A-002** `[User]` A tenant **manually promotes** a guest to `tenant` (no self-service elevation). → BR-A03
- **REQ-A-003** `[User]` Role is the existing `members.role` TEXT value (`guest`/`tenant`) — **no roles table, no roleId**. → BR-A04
- **REQ-A-004** `[Inferred]` Passwords are stored hashed (stdlib `scrypt` + per-user salt); login establishes an HMAC-signed session cookie; logout clears it. → BR-A05, BR-A06
- **REQ-A-005** `[Inferred]` Usernames are unique (case-insensitive). → BR-A02

## What the role changes (only two things)

- **REQ-R-001** `[Explicit]` **Bills:** only active **tenants** are in `bill_shares`; guests never owe rent. (Unchanged v1 invariant.) → BR-R01
- **REQ-R-002** `[Explicit]` **Access:** tenants get the dashboard + management (create bills, manage rules); guests get only view-rules / report / pay. → BR-R02
- **REQ-R-003** `[Explicit]` Everything else is identical for both roles: both are finable, can report a fine, and can pay / see their dues. → BR-R03

## Guest experience (web, logged in as a guest)

- **REQ-G-001** `[Explicit]` A guest's **welcome page** shows a personalized hello, the **rules as a menu** (emoji + amount), a fun **Hall of Shame**, and actions: **I'll behave / Report / Pay**. → BR-G01
- **REQ-G-002** `[Explicit]` A guest can **report a fine** (on any active member) → a `pending` fine via the v1 `fines` service. → BR-G02
- **REQ-G-003** `[Explicit]` A guest can **pay**: the pay screen shows the **wallet UPI QR** (`WALLET_UPI_QR_URL`) + their unpaid fines + a **mark-paid** action. Still **no money movement** (a claim). → BR-G03
- **REQ-G-004** `[Inferred]` Every guest action is scoped to the **logged-in** member — a guest acts only as themselves. → BR-G04

## Getting here (NEW — `[User]`, "very important")

- **REQ-L-001** `[User]` On the shared guest page, a guest can **see the flat on a map**. Prefer opening it in **whatever map app the guest has** (native app chooser), not a hard-coded one. → BR-L01
- **REQ-L-002** `[User]` The guest can **copy the address** in a format that pastes straight into Uber/Ola/Rapido. → BR-L02
- **REQ-L-003** `[User]` Offer **ride booking** with the flat pre-filled as the destination: show **Uber** and **Ola** options (deep links); Rapido falls back to copy-address. → BR-L03
- **REQ-L-004** `[Inferred]` Location comes from **config** (flat address + lat/lng in `.env`). If unset, the section degrades gracefully (address-only, or hidden). → BR-L04

## NFC `/s/<spot>`

- **REQ-N-001** `[Explicit]` `/s/<spot>` renders that spot's contextual page; the **six spots** map to DESIGN's content (kitchen → report pre-filtered to kitchen rules, balcony → smoking, bathroom → cleanliness, etc.). → BR-N01, BR-N02
- **REQ-N-002** `[Explicit]` The **same** sticker shows a **logged-in tenant** the management view and a **guest / not-logged-in** visitor the guest view. → BR-N03

## Platform

- **REQ-P-001** `[Inferred]` `members` evolves via idempotent `ALTER TABLE ADD COLUMN` (no migration framework). → BR-P01
- **REQ-P-002** `[Inferred]` Web pages still boot with no bot token (v1 BR-060 holds); pay degrades if no wallet QR; Getting here degrades if no location config. → BR-P02

(No open questions — the accounts model is decided. See overview → Decisions.)

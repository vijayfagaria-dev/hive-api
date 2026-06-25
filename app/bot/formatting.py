"""Message text builders — pure functions, no aiogram, no DB. Unit-testable.

Plain text + emoji (no parse_mode), so we never have to escape names/rule text.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

BILL_LABELS = {
    "rent": "🏠 Rent",
    "house_help": "🧹 House help",
    "electricity": "💡 Electricity",
    "water": "🚰 Water",
}


def rupees(n: int) -> str:
    return f"₹{n:,}"


def bill_label(bill_type: str) -> str:
    return BILL_LABELS.get(bill_type, bill_type)


def pot_text(total: int, count: int) -> str:
    if count == 0:
        return "🫙 The pot is empty — no confirmed fines yet."
    fines = "fine" if count == 1 else "fines"
    return f"🫙 The pot holds {rupees(total)} from {count} confirmed {fines}."


def fine_card_text(
    *, accused: str, accuser: str, rule_text: Optional[str], amount: int, cooling_hours: int
) -> str:
    reason = rule_text or "(no specific rule)"
    return (
        f"🚨 New fine: {accused} — {rupees(amount)}\n"
        f"“{reason}”\n"
        f"Reported by {accuser}. Auto-confirms in {cooling_hours}h unless disputed."
    )


def disputed_card_text(*, accused: str, amount: int, by: str) -> str:
    return (
        f"⚖️ Disputed: {accused}'s {rupees(amount)} fine\n"
        f"Flagged by {by} — parked for the house to sort out. No auto-confirm."
    )


def dues_text(
    *, name: str, fines: list[Mapping], shares: list[Mapping], total: int
) -> str:
    if total == 0:
        return f"✅ {name}, you're all settled — no dues."
    lines = [f"📋 {name}, you owe {rupees(total)}:"]
    if fines:
        lines.append("\nFines:")
        for f in fines:
            lines.append(f"  • {f['rule_text'] or '(no rule)'} — {rupees(f['amount'])}")
    if shares:
        lines.append("\nBill shares:")
        for s in shares:
            lines.append(f"  • {bill_label(s['type'])} {s['month']} — {rupees(s['share_amount'])}")
    lines.append("\nTap a button below to mark something paid.")
    return "\n".join(lines)


def all_dues_text(rows: list[Mapping]) -> str:
    """The whole-flat dues table (/dues all), biggest debtor first."""
    owing = [r for r in rows if r["total"] > 0]
    if not owing:
        return "✅ Nobody owes anything — the flat's all square."
    lines = ["📋 Who owes what:"]
    for r in owing:
        lines.append(f"  • {r['name']} — {rupees(r['total'])}")
    return "\n".join(lines)


def bill_card_text(
    *, bill_type: str, total: int, month: str, shares: list[Mapping]
) -> str:
    n = len(shares)
    way = "way" if n == 1 else "ways"
    lines = [f"🧾 {bill_label(bill_type)} — {rupees(total)} for {month}, split {n} {way}:"]
    for s in shares:
        tick = "✅" if s["paid"] else "⬜"
        lines.append(f"  {tick} {s['name']} — {rupees(s['share_amount'])}")
    lines.append("\nTap a name below once they've paid their share.")
    return "\n".join(lines)


def rules_overview_text(favorites: Iterable[Mapping], categories: Iterable[str]) -> str:
    fav_lines = [f"  ⭐ {r['text']} — {rupees(r['fine_amount'])}" for r in favorites]
    cats = ", ".join(categories)
    return (
        "📜 House rules — the usual suspects:\n"
        + ("\n".join(fav_lines) if fav_lines else "  (no favorites yet)")
        + f"\n\nBrowse a category below ({cats})."
    )


def rules_category_text(category: str, rules: Iterable[Mapping]) -> str:
    lines = [f"📜 {category} rules:"]
    for r in rules:
        star = "⭐ " if r["is_favorite"] else ""
        lines.append(f"  • {star}{r['text']} — {rupees(r['fine_amount'])}")
    return "\n".join(lines)

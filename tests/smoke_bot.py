"""Phase 3 offline integration test — drive the dispatcher with synthetic
Telegram updates, no network. A RecordingBot captures outgoing API calls; we
assert both DB side effects and message text.

    .venv/Scripts/python.exe tests/smoke_bot.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_bot_{uuid.uuid4().hex}.db")
os.environ["COOLING_HOURS"] = "12"

from aiogram import Bot  # noqa: E402
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage  # noqa: E402
from aiogram.types import Message, Update  # noqa: E402

from app import db as dbm, fines, queries  # noqa: E402
from app.bot import callbacks as cb  # noqa: E402
from app.bot.setup import create_dispatcher  # noqa: E402

GROUP = -100123  # a group chat id
_uid = 0


def next_update_id():
    global _uid
    _uid += 1
    return _uid


class RecordingBot(Bot):
    """A Bot whose API calls are recorded instead of sent."""

    def __init__(self):
        super().__init__(token="123456:TESTTOKENrecording0000000000000000000")
        self.sent = []

    async def __call__(self, method, request_timeout=None):
        self.sent.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message.model_validate(
                {"message_id": len(self.sent), "date": 0,
                 "chat": {"id": GROUP, "type": "group"}, "text": getattr(method, "text", "") or ""}
            )
        return True

    def pop_last(self, kind):
        for m in reversed(self.sent):
            if isinstance(m, kind):
                return m
        raise AssertionError(f"no {kind.__name__} recorded")


def msg_update(uid, first_name, text):
    return Update.model_validate({
        "update_id": next_update_id(),
        "message": {
            "message_id": next_update_id(), "date": 0,
            "chat": {"id": GROUP, "type": "group"},
            "from": {"id": uid, "is_bot": False, "first_name": first_name},
            "text": text,
        },
    })


def cb_update(uid, first_name, data, with_message=True):
    cq = {
        "id": f"c{next_update_id()}", "chat_instance": "ci",
        "from": {"id": uid, "is_bot": False, "first_name": first_name},
        "data": data,
    }
    if with_message:
        cq["message"] = {
            "message_id": next_update_id(), "date": 0,
            "chat": {"id": GROUP, "type": "group"},
            "from": {"id": 999, "is_bot": True, "first_name": "DenBot"},
            "text": "(prev)",
        }
    return Update.model_validate({"update_id": next_update_id(), "callback_query": cq})


def kb_callback_datas(method):
    """All callback_data strings in a method's reply_markup."""
    out = []
    rm = getattr(method, "reply_markup", None)
    if rm and getattr(rm, "inline_keyboard", None):
        for row in rm.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    out.append(btn.callback_data)
    return out


UID_A, UID_B = 1001, 1002  # Amit (founder), Rohit


async def main():
    db = await dbm.connect()
    bot = RecordingBot()
    dp = create_dispatcher(db)

    async def feed(update):
        await dp.feed_update(bot, update)

    async def latest_fine():
        # By id, not ts — two fines in the same second tie on ts.
        rows = await db.execute_fetchall("SELECT * FROM fines ORDER BY id DESC LIMIT 1")
        return rows[0]

    try:
        # 1) Founder bootstrap: first /start on an empty flat creates Amit.
        await feed(msg_update(UID_A, "Amit", "/start"))
        amit = await queries.get_member_by_telegram(db, UID_A)
        assert amit is not None and amit["is_active"] and amit["role"] == "tenant"
        assert "founding tenant" in bot.pop_last(SendMessage).text
        print("ok founder bootstrap via /start")

        # 2) Amit adds Rohit (unlinked tenant).
        await feed(msg_update(UID_A, "Amit", "/addtenant Rohit"))
        assert "Added Rohit" in bot.pop_last(SendMessage).text
        rohit_row = next(m for m in await queries.list_unlinked_tenants(db) if m["name"] == "Rohit")
        print("ok /addtenant created an unlinked tenant")

        # 3) Rohit /start -> offered a claim button -> claims it.
        await feed(msg_update(UID_B, "Rohit", "/start"))
        claim_data = kb_callback_datas(bot.pop_last(SendMessage))
        assert cb.Claim(member_id=rohit_row["id"]).pack() in claim_data
        await feed(cb_update(UID_B, "Rohit", cb.Claim(member_id=rohit_row["id"]).pack()))
        rohit = await queries.get_member_by_telegram(db, UID_B)
        assert rohit is not None and rohit["id"] == rohit_row["id"]
        print("ok claim flow links Rohit's telegram id")

        # 4) /pot when empty.
        await feed(msg_update(UID_A, "Amit", "/pot"))
        assert "empty" in bot.pop_last(SendMessage).text
        print("ok /pot empty")

        # 5) /fine flow: Amit picks a favorite rule -> accused picker excludes Amit,
        #    and INCLUDES guests (guests are finable, v2 BR-R03).
        zoe = await queries.add_member(db, "Zoe", role="guest")
        await feed(msg_update(UID_A, "Amit", "/fine"))
        fav = (await queries.list_favorite_rules(db))[0]
        await feed(cb_update(UID_A, "Amit", cb.FineRule(rule_id=fav["id"]).pack()))
        who_datas = kb_callback_datas(bot.pop_last(EditMessageText))
        assert cb.FineWho(rule_id=fav["id"], member_id=rohit["id"]).pack() in who_datas
        assert cb.FineWho(rule_id=fav["id"], member_id=amit["id"]).pack() not in who_datas
        assert cb.FineWho(rule_id=fav["id"], member_id=zoe).pack() in who_datas
        print("ok /fine picker excludes the reporter, includes guests")

        # ...Amit fines Rohit -> a pending fine + a card with a Dispute button.
        await feed(cb_update(UID_A, "Amit", cb.FineWho(rule_id=fav["id"], member_id=rohit["id"]).pack()))
        card = bot.pop_last(EditMessageText)
        assert "New fine" in card.text and "Rohit" in card.text
        fine_row = await latest_fine()
        assert fine_row["status"] == "pending" and fine_row["member_id"] == rohit["id"] and fine_row["added_by"] == amit["id"]
        assert cb.FineDispute(fine_id=fine_row["id"]).pack() in kb_callback_datas(card)
        print("ok /fine creates a pending fine vs Rohit with a Dispute button")

        # 6) Rohit disputes that fine -> status disputed.
        await feed(cb_update(UID_B, "Rohit", cb.FineDispute(fine_id=fine_row["id"]).pack()))
        assert (await queries.get_fine(db, fine_row["id"]))["status"] == "disputed"
        assert "Disputed" in bot.pop_last(EditMessageText).text
        print("ok Dispute button moves the fine to disputed")

        # 7) A second fine that confirms via the sweep, then Rohit pays it from /dues.
        await feed(cb_update(UID_A, "Amit", cb.FineWho(rule_id=fav["id"], member_id=rohit["id"]).pack()))
        fine2 = await latest_fine()
        await db.execute("UPDATE fines SET confirm_deadline='2000-01-01T00:00:00Z' WHERE id=?", (fine2["id"],))
        await db.commit()
        assert await fines.sweep_due(db) == [fine2["id"]]
        await feed(msg_update(UID_B, "Rohit", "/dues"))
        dues_msg = bot.pop_last(SendMessage)
        assert "you owe" in dues_msg.text
        assert cb.FinePay(fine_id=fine2["id"]).pack() in kb_callback_datas(dues_msg)
        await feed(cb_update(UID_B, "Rohit", cb.FinePay(fine_id=fine2["id"]).pack()))
        assert (await queries.get_fine(db, fine2["id"]))["paid"] == 1
        print("ok confirmed fine shows in /dues and the pay button marks it paid")

        # FinePay guard: Amit can't pay Rohit's fine.
        await feed(cb_update(UID_A, "Amit", cb.FinePay(fine_id=fine2["id"]).pack()))
        ans = bot.pop_last(AnswerCallbackQuery)
        assert ans.show_alert and "not your fine" in ans.text.lower()
        print("ok FinePay rejects paying someone else's fine")

        # 8) /bill snapshots shares for both active tenants and they sum to the total.
        await feed(msg_update(UID_A, "Amit", "/bill electricity 2400"))
        bill_msg = bot.pop_last(SendMessage)
        assert "Electricity" in bill_msg.text
        bill = await queries.get_bill(db, (await db.execute_fetchall("SELECT id FROM bills ORDER BY id DESC LIMIT 1"))[0][0])
        shares = await queries.list_bill_shares(db, bill["id"])
        assert len(shares) == 2 and sum(s["share_amount"] for s in shares) == 2400
        print("ok /bill snapshots shares summing exactly to the total")

        # 8b) Rohit pays HIS share from /dues -> DuesShare; the view STAYS dues (not a bill card).
        await feed(msg_update(UID_B, "Rohit", "/dues"))
        dues2 = bot.pop_last(SendMessage)
        dues_datas = kb_callback_datas(dues2)
        assert cb.DuesShare(bill_id=bill["id"]).pack() in dues_datas
        assert not any(d.startswith("bshr:") for d in dues_datas)  # no bill-card BillShare in dues
        await feed(cb_update(UID_B, "Rohit", cb.DuesShare(bill_id=bill["id"]).pack()))
        edited = bot.pop_last(EditMessageText)
        assert "split" not in edited.text  # stayed a dues view, NOT the shared bill card
        paid = {s["member_id"]: s["paid"] for s in await queries.list_bill_shares(db, bill["id"])}
        assert paid[rohit["id"]] == 1 and paid[amit["id"]] == 0
        print("ok /dues share-pay uses DuesShare and keeps the dues view private")

        # 9) Amit pays the LAST share from the bill card -> keyboard is cleared (not an empty markup).
        await feed(cb_update(UID_A, "Amit", cb.BillShare(bill_id=bill["id"], member_id=amit["id"]).pack()))
        last = bot.pop_last(EditMessageText)
        assert last.reply_markup is None
        assert all(s["paid"] for s in await queries.list_bill_shares(db, bill["id"]))
        print("ok bill-card last-share pay clears the keyboard")

        # 10) /dues all renders the whole-flat table.
        await feed(msg_update(UID_A, "Amit", "/dues all"))
        all_text = bot.pop_last(SendMessage).text
        assert "owes" in all_text or "square" in all_text
        print("ok /dues all renders the whole-flat table")

        # 11) Robustness: a callback whose message is gone (old tap) must not crash.
        await feed(cb_update(UID_A, "Amit", cb.FineWho(rule_id=fav["id"], member_id=rohit["id"]).pack()))
        stale_fine = await latest_fine()
        await feed(cb_update(UID_B, "Rohit", cb.FineDispute(fine_id=stale_fine["id"]).pack(), with_message=False))
        assert (await queries.get_fine(db, stale_fine["id"]))["status"] == "disputed"
        print("ok callback with no message disputes without crashing (safe_edit guard)")

        # 12) Unregistered user is nudged to /start.
        await feed(msg_update(9999, "Stranger", "/dues"))
        assert "/start" in bot.pop_last(SendMessage).text
        print("ok unregistered user is nudged to /start")

        print("\nPHASE-3 BOT SMOKE: ALL CHECKS PASSED")
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

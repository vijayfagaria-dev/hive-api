"""Webhook + health — the only non-API, non-bot HTTP surface.

    HIVE_TEST_MODE=web  .venv/Scripts/python.exe tests/smoke_web.py   # bot disabled -> webhook 404
    HIVE_TEST_MODE=bot  .venv/Scripts/python.exe tests/smoke_web.py   # fake token -> secret guard
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODE = os.environ.get("HIVE_TEST_MODE", "web")
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_web_{uuid.uuid4().hex}.db")
os.environ["WEBHOOK_SECRET"] = "testsecret"
os.environ.pop("WEBHOOK_BASE_URL", None)  # no network set_webhook
if MODE == "bot":
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456:FAKEtoken000000000000000000000000000"
else:
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def main():
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        print("ok /health")

        if MODE == "web":
            # Webhook is inert when the bot is disabled (BR-060).
            assert client.post(settings.webhook_path, json={"update_id": 1}).status_code == 404
            print("ok webhook 404 when bot disabled (BR-060)")
        else:
            # Secret guard (BR-061): wrong header -> 403.
            bad = client.post(
                settings.webhook_path, json={"update_id": 1},
                headers={"X-Telegram-Bot-Api-Secret-Token": "WRONG"},
            )
            assert bad.status_code == 403, bad.status_code
            # Correct secret + an unmatched update -> 200, no outbound send.
            ok = client.post(
                settings.webhook_path,
                json={"update_id": 2, "message": {
                    "message_id": 1, "date": 0, "chat": {"id": -100, "type": "group"},
                    "from": {"id": 5, "is_bot": False, "first_name": "X"}, "text": "/zzz"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "testsecret"},
            )
            assert ok.status_code == 200, ok.status_code
            # A malformed body must still ACK 200 (no 500 -> no Telegram retry storm).
            bad_body = client.post(
                settings.webhook_path, json={"update_id": "not-an-int", "message": 123},
                headers={"X-Telegram-Bot-Api-Secret-Token": "testsecret"},
            )
            assert bad_body.status_code == 200, bad_body.status_code
            print("ok webhook 403/200 secret guard + malformed -> 200 (BR-061)")

    print(f"\nWEBHOOK SMOKE [{MODE}]: PASSED")


if __name__ == "__main__":
    main()

"""Health + retired-bot surface check (the Telegram bot was removed in v4).

    .venv/bin/python3 tests/smoke_web.py
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_web_{uuid.uuid4().hex}.db")
os.environ["SECRET_KEY"] = "testsecret"


def main():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        print("ok /health")

        # The Telegram bot is retired: no bot wired, and the old webhook path 404s.
        assert not hasattr(app.state, "bot")
        assert client.post("/telegram/webhook/anything", json={"update_id": 1}).status_code == 404
        print("ok Telegram bot retired (no bot wired; old webhook path 404s)")

        # Web Push public key endpoint is public and null when VAPID is unconfigured
        # (the in-app feed + email fallback still work).
        assert client.get("/api/push/public-key").json()["key"] is None
        print("ok /api/push/public-key is null when Web Push unconfigured")

    print("\nWEB SMOKE: PASSED")


if __name__ == "__main__":
    main()

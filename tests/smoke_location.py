""""Getting here" link builder — all branches (full coords, address-only, none,
non-numeric, nan/inf/off-globe). (The card render is covered by the frontend +
/api/me in tests/smoke_api.py.)

    .venv/Scripts/python.exe tests/smoke_location.py
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_loc_{uuid.uuid4().hex}.db")
os.environ["WEBHOOK_SECRET"] = "testsecret"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ["FLAT_ADDRESS"] = "221B Baker Street, Bengaluru"
os.environ["FLAT_LAT"] = "12.9716"
os.environ["FLAT_LNG"] = "77.5946"
os.environ["FLAT_PLACE_NAME"] = "Hive"

from app.services.location import getting_here_links  # noqa: E402


def ns(**kw):
    base = dict(flat_lat="", flat_lng="", flat_address="", flat_place_name="")
    base.update(kw)
    return SimpleNamespace(**base)


def unit_checks():
    full = getting_here_links(ns(flat_lat="12.9716", flat_lng="77.5946",
                                 flat_address="221B Baker St", flat_place_name="Hive"))
    assert full is not None
    assert "destination=12.9716,77.5946" in full["directions"]  # literal comma (canonical)
    assert full["geo"].startswith("geo:12.9716,77.5946")        # android app chooser
    assert "m.uber.com/ul" in full["uber"] and "12.9716" in full["uber"]
    assert "book.olacabs.com" in full["ola"] and "drop_lat=12.9716" in full["ola"]
    # Rapido: Android intent URL — opens the app with the drop pre-filled, else web fallback.
    assert "scheme=rapido" in full["rapido"] and "destinationLat=12.9716" in full["rapido"]
    assert "browser_fallback_url=" in full["rapido"] and "rapido.bike" in full["rapido"]
    print("ok full coords -> directions + geo + uber + ola + rapido links")

    assert getting_here_links(ns(flat_address="221B")) == {"address": "221B"}  # address only
    assert getting_here_links(ns()) is None                                     # nothing set
    assert getting_here_links(ns(flat_lat="abc", flat_lng="77", flat_address="221B")) == {"address": "221B"}
    # nan / inf / off-globe coords must degrade, never build a broken link.
    assert getting_here_links(ns(flat_lat="nan", flat_lng="77.5", flat_address="221B")) == {"address": "221B"}
    assert getting_here_links(ns(flat_lat="inf", flat_lng="77.5", flat_address="221B")) == {"address": "221B"}
    assert getting_here_links(ns(flat_lat="200", flat_lng="77.5", flat_address="221B")) == {"address": "221B"}
    print("ok degrades gracefully: address-only / none / non-numeric / nan / inf / off-globe")


def main():
    unit_checks()
    print("\nLOCATION SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()

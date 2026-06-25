"""Getting here — build the guest navigation links from the flat's location config.

Pure + dependency-free (stdlib urllib only), so it's easy to test and the
welcome page can render it. Returns None when there's nothing useful to show, so
the card degrades gracefully (BR-L04). Deep-link formats verified 2026-06 against
Uber's and Ola's deep-linking docs.
"""

from __future__ import annotations

import math
from typing import Optional
from urllib.parse import quote, urlencode


def getting_here_links(settings) -> Optional[dict]:
    """A dict of navigation links/text for the welcome card, or None if unset.

    With valid coordinates: map directions, a geo: link (Android app chooser),
    and Uber + Ola ride deep links (drop pre-filled). With only an address: just
    the copyable address. With neither: None (card hidden).
    """
    lat = (settings.flat_lat or "").strip()
    lng = (settings.flat_lng or "").strip()
    address = (settings.flat_address or "").strip()
    place = (settings.flat_place_name or "").strip() or "Hive"

    has_coords = bool(lat and lng)
    if has_coords:
        try:
            flat, flng = float(lat), float(lng)
        except ValueError:
            has_coords = False  # not a number -> treat as address-only
        else:
            # Reject nan/inf and off-globe values so we never render a broken
            # map/ride link (BR-L04); float() alone accepts "nan"/"inf"/"1e9".
            if not (math.isfinite(flat) and math.isfinite(flng)
                    and -90 <= flat <= 90 and -180 <= flng <= 180):
                has_coords = False

    if not has_coords:
        return {"address": address} if address else None

    coords = f"{lat},{lng}"  # validated numeric strings — already URL-safe
    uber = {
        "action": "setPickup",
        "pickup": "my_location",
        "dropoff[latitude]": lat,
        "dropoff[longitude]": lng,
        "dropoff[nickname]": place,
    }
    if address:
        uber["dropoff[formatted_address]"] = address
    ola = {"drop_lat": lat, "drop_lng": lng, "utm_source": "hive"}

    return {
        "address": address,
        "place": place,
        # Google Maps directions — works everywhere; in India it also offers
        # Uber/Ola/Rapido inside the app.
        "directions": "https://www.google.com/maps/dir/?api=1&destination=" + coords,
        # geo: opens the device's own map app (Android's native chooser).
        "geo": f"geo:{coords}?q={coords}({quote(place)})",
        "uber": "https://m.uber.com/ul/?" + urlencode(uber),
        "ola": "https://book.olacabs.com/?" + urlencode(ola),
        # Rapido has no public drop-prefill deep link — open the app (paste the
        # copied address). The rapido.bike universal link opens the app if installed.
        "rapido": "https://www.rapido.bike/",
    }

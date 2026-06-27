"""Getting here — build the guest navigation links from the flat's location config.

Pure + dependency-free (stdlib urllib only). Returns None when there's nothing
useful to show, so the welcome card degrades gracefully. Deep-link formats
verified against Uber's and Ola's docs.
"""

from __future__ import annotations

import math
from typing import Optional
from urllib.parse import quote, urlencode


def getting_here_links(settings) -> Optional[dict]:
    """Navigation links/text for the welcome card, or None if location is unset."""
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
            # Reject nan/inf and off-globe values so we never render a broken link.
            if not (
                math.isfinite(flat)
                and math.isfinite(flng)
                and -90 <= flat <= 90
                and -180 <= flng <= 180
            ):
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
    # Rapido has no public web-booking universal link (unlike Uber/Ola), so use an
    # Android intent URL: it opens the Rapido app with the drop pre-filled if installed,
    # else falls back to the web. (iOS Rapido deep-linking is unreliable; iOS just opens
    # the fallback.) Mirrors Uber/Ola: coordinates + place are passed, not a bare home page.
    rapido_q = urlencode(
        {"destinationLat": lat, "destinationLng": lng, "destinationAddress": place},
        quote_via=quote,
    )
    rapido = (
        f"intent://book?{rapido_q}"
        "#Intent;scheme=rapido;package=com.rapido.passenger;"
        f"S.browser_fallback_url={quote('https://www.rapido.bike/', safe='')};end"
    )

    return {
        "address": address,
        "place": place,
        "directions": "https://www.google.com/maps/dir/?api=1&destination=" + coords,
        "geo": f"geo:{coords}?q={coords}({quote(place)})",
        "uber": "https://m.uber.com/ul/?" + urlencode(uber),
        "ola": "https://book.olacabs.com/?" + urlencode(ola),
        "rapido": rapido,
    }

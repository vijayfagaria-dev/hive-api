"""Conservative server-side text cleaning — defense-in-depth against stored XSS.

Proposal bodies/comments are user text the frontend renders as markdown. We strip
raw HTML tags here (so a `<script>` can never be stored) and cap length; the
frontend is still responsible for safe markdown rendering.
"""

from __future__ import annotations

import re
from typing import Optional

_TAG = re.compile(r"<[^>]*>")


def clean(text: Optional[str], max_len: int = 5000) -> Optional[str]:
    if text is None:
        return None
    stripped = _TAG.sub("", text).replace("\x00", "").strip()
    return stripped[:max_len]

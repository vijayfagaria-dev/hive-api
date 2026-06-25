"""Configuration, loaded from the environment (.env).

Keep it tiny: a frozen dataclass read once at import. Secrets live in .env
(gitignored) — never hard-code them here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # --- Telegram ---
    # Empty token is allowed: the web app still boots (handy while scaffolding /
    # before @BotFather is set up). The bot just stays disabled.
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    # Public base URL Telegram should POST updates to, e.g. https://hive.example.com
    webhook_base_url: str = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
    # Shared secret in the webhook path + Telegram's secret-token header.
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "hive-dev-secret").strip()

    # --- Web sessions (v2) ---
    # Signs the login session cookie. Falls back to the webhook secret if unset.
    session_secret: str = os.getenv("SECRET_KEY", "").strip()
    # Send the session cookie only over HTTPS. Off by default so http://localhost
    # dev works; set COOKIE_SECURE=true in production (behind TLS).
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")

    # --- Storage ---
    database_path: str = os.getenv("DATABASE_PATH", "hive.db").strip()

    # --- Fine workflow (Layer 1: cooling window) ---
    # A pending fine auto-confirms after this many hours unless disputed.
    # DESIGN.md recommends ~12h for small fines.
    cooling_hours: int = _int("COOLING_HOURS", 12)
    # How often the background sweep promotes overdue pending fines.
    sweep_interval_seconds: int = _int("SWEEP_INTERVAL_SECONDS", 300)

    # --- Getting here (v2): the flat's location for the guest navigation card ---
    flat_address: str = os.getenv("FLAT_ADDRESS", "").strip()
    flat_lat: str = os.getenv("FLAT_LAT", "").strip()
    flat_lng: str = os.getenv("FLAT_LNG", "").strip()
    flat_place_name: str = os.getenv("FLAT_PLACE_NAME", "").strip()

    # --- Misc ---
    wallet_upi_qr_url: str = os.getenv("WALLET_UPI_QR_URL", "").strip()

    @property
    def bot_enabled(self) -> bool:
        return bool(self.bot_token)

    @property
    def secret_key(self) -> str:
        """Key for signing session cookies — a dedicated SECRET_KEY, else reuse
        the webhook secret so a single configured secret covers everything."""
        return self.session_secret or self.webhook_secret

    @property
    def webhook_path(self) -> str:
        """Unguessable path so randoms can't POST fake updates."""
        return f"/telegram/webhook/{self.webhook_secret}"

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url}{self.webhook_path}" if self.webhook_base_url else ""


settings = Settings()

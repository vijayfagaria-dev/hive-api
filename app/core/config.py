"""Centralized configuration, loaded once from the environment (.env).

A frozen dataclass read at import. Secrets live in .env (gitignored) — never
hard-code them here. This is the single source of settings for every layer.
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
    # --- App ---
    # Public base URL of the web app, used to deep-link notifications back to a
    # complaint (e.g. https://hive.example.com). Empty -> links are omitted.
    app_base_url: str = os.getenv("APP_BASE_URL", "").strip().rstrip("/")

    # --- Web sessions ---
    # Signs the login session cookie. SECRET_KEY preferred; WEBHOOK_SECRET kept as
    # a legacy fallback so existing .env files keep working after the bot retired.
    session_secret: str = os.getenv("SECRET_KEY", "").strip()
    legacy_secret: str = os.getenv("WEBHOOK_SECRET", "hive-dev-secret").strip()
    # Send the session cookie only over HTTPS. Off by default so http://localhost
    # dev works; set COOKIE_SECURE=true in production (behind TLS).
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")

    # --- Storage ---
    database_path: str = os.getenv("DATABASE_PATH", "hive.db").strip()

    # --- Complaint cooling window (Layer 1) ---
    # A pending complaint auto-confirms after this many hours unless disputed.
    cooling_hours: int = _int("COOLING_HOURS", 12)
    # How often the background sweep auto-confirms overdue complaints AND finalizes
    # votes whose window has closed.
    sweep_interval_seconds: int = _int("SWEEP_INTERVAL_SECONDS", 300)

    # --- Notifications: Web Push (VAPID) + email, on top of the in-app feed ---
    vapid_public_key: str = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    vapid_private_key: str = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    vapid_subject: str = os.getenv("VAPID_SUBJECT", "mailto:admin@hive.local").strip()
    smtp_host: str = os.getenv("SMTP_HOST", "").strip()
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_username: str = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password: str = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from: str = os.getenv("SMTP_FROM", "Hive <no-reply@hive.local>").strip()
    smtp_starttls: bool = os.getenv("SMTP_STARTTLS", "true").strip().lower() in ("1", "true", "yes")

    # WhatsApp Cloud API (Meta, official). Proactive pings must use a pre-approved
    # TEMPLATE with one body variable {{1}}. Empty token/phone-id -> skipped.
    whatsapp_token: str = os.getenv("WHATSAPP_TOKEN", "").strip()
    whatsapp_phone_id: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    whatsapp_template: str = os.getenv("WHATSAPP_TEMPLATE_NAME", "hive_alert").strip()
    whatsapp_lang: str = os.getenv("WHATSAPP_TEMPLATE_LANG", "en").strip()
    whatsapp_api_version: str = os.getenv("WHATSAPP_API_VERSION", "v21.0").strip()

    # --- Complaint workflow (proof + accept/deny + voting) ---
    vote_window_hours: int = _int("VOTE_WINDOW_HOURS", 24)
    proof_storage_dir: str = os.getenv("PROOF_STORAGE_DIR", "proofs").strip()
    max_proof_bytes: int = _int("MAX_PROOF_BYTES", 8 * 1024 * 1024)
    max_complaints_per_day: int = _int("MAX_COMPLAINTS_PER_DAY", 8)
    duplicate_window_hours: int = _int("DUPLICATE_WINDOW_HOURS", 6)

    # --- Getting here: the flat's location for the guest navigation card ---
    flat_address: str = os.getenv("FLAT_ADDRESS", "").strip()
    flat_lat: str = os.getenv("FLAT_LAT", "").strip()
    flat_lng: str = os.getenv("FLAT_LNG", "").strip()
    flat_place_name: str = os.getenv("FLAT_PLACE_NAME", "").strip()

    # --- Misc ---
    wallet_upi_qr_url: str = os.getenv("WALLET_UPI_QR_URL", "").strip()

    @property
    def secret_key(self) -> str:
        """Session-cookie signing key — dedicated SECRET_KEY, else the legacy one."""
        return self.session_secret or self.legacy_secret

    @property
    def async_database_url(self) -> str:
        """Runtime async URL (FastAPI app). Absolute paths already start with '/',
        so the single-slash form yields the correct '////abs/path'."""
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def sync_database_url(self) -> str:
        """Sync URL used by Alembic migrations (offline CLI)."""
        return f"sqlite:///{self.database_path}"

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_private_key and self.vapid_public_key)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.whatsapp_token and self.whatsapp_phone_id)


settings = Settings()

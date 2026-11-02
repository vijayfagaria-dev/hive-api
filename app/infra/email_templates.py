"""Branded transactional email templates (HTML + plain-text twins).

Email HTML is its own dialect: table layout, inline styles, no web fonts or CSS
variables, so the brand ("Daylight Ledger" — cream paper, ink, acid lime) is baked
in as hex. Every dynamic value is HTML-escaped. Each builder returns a ready
`mailer.Message`.
"""

from __future__ import annotations

from html import escape
from typing import Optional

from app.core.config import settings
from app.domain.enums import OtpPurpose
from app.infra.mailer import Message

# Brand palette (hex of the web app's OKLCH tokens).
CREAM = "#F4F2ED"
CARD = "#FEFDFA"
INK = "#1D1A14"
MUTED = "#66635C"
BORDER = "#E0DED8"
ACID = "#ABD72E"
ACID_INK = "#1F2F0B"
ACID_SOFT = "#EEF5D9"
DANGER = "#D73337"

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "'SF Mono',SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"

_COPY = {
    OtpPurpose.REGISTER: {
        "subject": "{code} is your Hive verification code",
        "eyebrow": "Verify your email",
        "headline": "Almost in.",
        "lead": "Use this code to finish creating your Hive account{who}.",
        "footnote": "Didn't try to join Hive? You can ignore this email — no account is created without the code.",
    },
    OtpPurpose.PASSWORD_RESET: {
        "subject": "{code} is your Hive password reset code",
        "eyebrow": "Password reset",
        "headline": "Reset your password.",
        "lead": "Someone (hopefully you) asked to reset the password for your Hive account{who}. Enter this code to choose a new one.",
        "footnote": "Didn't ask for this? Ignore this email — your password stays the same and nobody can change it without this code.",
    },
    OtpPurpose.CHANGE_EMAIL: {
        "subject": "{code} — confirm your new email for Hive",
        "eyebrow": "Confirm new email",
        "headline": "Is this you?",
        "lead": "Enter this code in Hive to make this your account email{who}.",
        "footnote": "Didn't change your email on Hive? Ignore this — nothing changes without the code.",
    },
}


def _layout(*, preheader: str, eyebrow: str, headline: str, body_html: str, footnote: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light">
<title>{escape(headline)}</title>
</head>
<body style="margin:0;padding:0;background:{CREAM};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{CREAM};">
  <tr><td align="center" style="padding:32px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px;">
      <tr><td style="padding:0 4px 20px;font-family:{_MONO};font-size:12px;letter-spacing:4px;text-transform:uppercase;color:{INK};">
        <span style="display:inline-block;width:10px;height:10px;border-radius:5px;background:{ACID};margin-right:8px;vertical-align:middle;"></span>Hive
      </td></tr>
      <tr><td style="background:{CARD};border:1px solid {BORDER};border-radius:20px;padding:32px 28px;">
        <p style="margin:0;font-family:{_MONO};font-size:11px;letter-spacing:3px;text-transform:uppercase;color:{MUTED};">{escape(eyebrow)}</p>
        <h1 style="margin:12px 0 0;font-family:{_FONT};font-size:30px;line-height:1.1;font-weight:800;letter-spacing:-0.5px;color:{INK};">{escape(headline)}</h1>
        {body_html}
      </td></tr>
      <tr><td style="padding:20px 8px 0;font-family:{_FONT};font-size:12px;line-height:1.6;color:{MUTED};">
        {escape(footnote)}
        <br><br>Hive · the flat's ledger. This is an automated security email — replies aren't monitored.
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def otp_email(*, purpose: str, to: str, code: str, minutes: int, username: Optional[str] = None) -> Message:
    copy = _COPY[OtpPurpose(purpose)]
    who_text = f" ({username})" if username else ""
    lead_text = copy["lead"].format(who=who_text)
    lead_html = escape(copy["lead"]).format(who=f" (<b>{escape(username)}</b>)" if username else "")
    spaced = f"{code[:3]} {code[3:]}"
    body_html = f"""
        <p style="margin:14px 0 0;font-family:{_FONT};font-size:15px;line-height:1.6;color:{MUTED};">{lead_html}</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 8px;">
          <tr><td align="center" style="background:{ACID_SOFT};border:1px solid {ACID};border-radius:16px;padding:20px 12px;">
            <div style="font-family:{_MONO};font-size:36px;line-height:1;font-weight:700;letter-spacing:10px;color:{ACID_INK};">{escape(spaced)}</div>
          </td></tr>
        </table>
        <p style="margin:12px 0 0;font-family:{_FONT};font-size:13px;line-height:1.6;color:{MUTED};">
          This code expires in <b style="color:{INK};">{minutes} minutes</b> and works once. Never share it — Hive will never ask you for it.
        </p>"""
    text = (
        f"{copy['headline']}\n\n{lead_text}\n\n"
        f"    {spaced}\n\n"
        f"This code expires in {minutes} minutes and works once. Never share it.\n\n"
        f"{copy['footnote']}\n\n— Hive"
    )
    return Message(
        to=to,
        subject=copy["subject"].format(code=code),
        text=text,
        html=_layout(
            preheader=f"Your code is {spaced}. It expires in {minutes} minutes.",
            eyebrow=copy["eyebrow"],
            headline=copy["headline"],
            body_html=body_html,
            footnote=copy["footnote"],
        ),
    )


def password_changed_email(*, to: str, username: str, how: str) -> Message:
    """Security notice after a password change/reset. `how` is 'changed' or 'reset'."""
    reset_url = f"{settings.app_base_url}/forgot-password" if settings.app_base_url else None
    button = (
        f"""<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 0;">
          <tr><td style="background:{INK};border-radius:999px;">
            <a href="{escape(reset_url)}" style="display:inline-block;padding:12px 22px;font-family:{_FONT};font-size:14px;font-weight:600;color:{CARD};text-decoration:none;">Secure my account →</a>
          </td></tr>
        </table>"""
        if reset_url
        else ""
    )
    body_html = f"""
        <p style="margin:14px 0 0;font-family:{_FONT};font-size:15px;line-height:1.6;color:{MUTED};">
          The password for your Hive account <b style="color:{INK};">{escape(username)}</b> was just {escape(how)}.
          Every other device was signed out.
        </p>
        <p style="margin:14px 0 0;font-family:{_FONT};font-size:15px;line-height:1.6;color:{MUTED};">
          <b style="color:{DANGER};">Wasn't you?</b> Reset your password right away and tell a flatmate.
        </p>
        {button}"""
    text = (
        f"The password for your Hive account {username} was just {how}. Every other device was signed out.\n\n"
        f"Wasn't you? Reset your password right away"
        + (f": {reset_url}" if reset_url else ".")
        + "\n\n— Hive"
    )
    return Message(
        to=to,
        subject="Your Hive password was " + how,
        text=text,
        html=_layout(
            preheader=f"Your Hive password was {how}.",
            eyebrow="Security notice",
            headline=f"Password {how}.",
            body_html=body_html,
            footnote="You're getting this because it's a security change on your account.",
        ),
    )

"""SAAS-028 — the platform's own outbound mail (setup links, SAAS-033
billing notices). Separate from services/mailer.py, which sends with a
school's own SMTP settings.

Configured from the environment only (PLATFORM_SMTP_*). When it isn't
configured, is_configured() is False and callers fall back to showing
the information on screen. The password never reaches a log or an
error message.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app

_log = logging.getLogger(__name__)


class PlatformMailError(RuntimeError):
    pass


def _cfg(key, default=None):
    return current_app.config.get(key, default)


def is_configured() -> bool:
    return bool(_cfg("PLATFORM_SMTP_HOST") and _cfg("PLATFORM_SMTP_FROM"))


def send(to_email: str, subject: str, body: str) -> None:
    """One plain-text mail. Raises PlatformMailError with a generic,
    secret-free message."""
    if not is_configured():
        raise PlatformMailError("platform SMTP is not configured")
    msg = MIMEMultipart("alternative")
    msg["From"] = f"منصتي <{_cfg('PLATFORM_SMTP_FROM')}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        server = smtplib.SMTP(_cfg("PLATFORM_SMTP_HOST"), int(_cfg("PLATFORM_SMTP_PORT") or 587), timeout=15)
        try:
            server.ehlo()
            if _cfg("PLATFORM_SMTP_TLS", True):
                server.starttls()
                server.ehlo()
            if _cfg("PLATFORM_SMTP_USERNAME"):
                server.login(_cfg("PLATFORM_SMTP_USERNAME"), _cfg("PLATFORM_SMTP_PASSWORD") or "")
            server.sendmail(_cfg("PLATFORM_SMTP_FROM"), [to_email], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
    except (smtplib.SMTPException, OSError) as e:
        # Type only: SMTP errors can echo the login exchange.
        _log.warning("platform mail failed: %s", type(e).__name__)
        raise PlatformMailError("تعذّر إرسال الإيميل من المنصة.") from None

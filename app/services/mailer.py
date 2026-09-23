"""SMTP mailer — per-school outbound email.

Reads SMTP settings from the School row. Password is stored
Fernet-encrypted; the raw value never touches disk. Encryption key
comes from `SMTP_CRYPTO_KEY` (or, as a dev fallback, from
`SECRET_KEY` — good enough for a demo, but production should always
set `SMTP_CRYPTO_KEY` explicitly).
"""

from __future__ import annotations

import base64
import hashlib
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from cryptography.fernet import Fernet, InvalidToken


class MailError(RuntimeError):
    pass


def _key() -> bytes:
    raw = (os.environ.get("SMTP_CRYPTO_KEY")
           or os.environ.get("SECRET_KEY")
           or "dev-secret")
    # Fernet needs a URL-safe 32-byte base64 key; hash whatever we got
    # into exactly that shape.
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext: str) -> str:
    if plaintext is None or plaintext == "":
        return ""
    return Fernet(_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return Fernet(_key()).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise MailError("تعذّر فك تشفير كلمة مرور SMTP — يرجى إعادة إدخالها.") from e


def is_configured(school) -> bool:
    return bool(school and school.smtp_host and school.smtp_from_email)


def _open_connection(school):
    server = smtplib.SMTP(school.smtp_host, school.smtp_port or 587, timeout=15)
    server.ehlo()
    if school.smtp_use_tls:
        server.starttls()
        server.ehlo()
    if school.smtp_username:
        password = decrypt(school.smtp_password_encrypted or "")
        server.login(school.smtp_username, password)
    return server


def send(school, to_email: str, subject: str, body: str,
         *, html: bool = False) -> None:
    """Sends one email. Raises MailError on any failure."""
    if not is_configured(school):
        raise MailError("SMTP غير مُهيّأ لهذه المدرسة.")
    from_name = school.smtp_from_name or school.name
    from_email = school.smtp_from_email
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
    try:
        server = _open_connection(school)
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"تعذّر الاتصال بخادم SMTP: {e}") from e
    try:
        server.sendmail(from_email, [to_email], msg.as_string())
    except smtplib.SMTPException as e:
        server.quit()
        raise MailError(f"فشل إرسال الإيميل: {e}") from e
    finally:
        try:
            server.quit()
        except Exception:
            pass


def test_connection(school) -> tuple[bool, str]:
    """Used by the admin's "اختبار الاتصال" button. Doesn't send an
    email — just proves the credentials work and the connection opens.
    Returns (ok, message)."""
    if not is_configured(school):
        return False, "أدخل بيانات SMTP أولاً وحفظها ثم اضغط اختبار."
    try:
        server = _open_connection(school)
        server.noop()
        server.quit()
        return True, f"تم الاتصال بنجاح مع {school.smtp_host}."
    except MailError as e:
        return False, str(e)
    except (smtplib.SMTPException, OSError) as e:
        return False, f"تعذّر الاتصال بـ {school.smtp_host}: {e}"

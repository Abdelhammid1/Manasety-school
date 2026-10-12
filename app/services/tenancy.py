"""SAAS-003 (2026-10-12) — tenant identity helpers.

Shared slug validation + the reserved-subdomain list that both the
model layer and (later) SAAS-004's host resolver will read from.
Kept in one place so the two never drift.

This file is intentionally minimal today — the full tenant
resolution middleware lands in SAAS-004 and extends this module.
"""

from __future__ import annotations

import re
from typing import Final


# Decision D8 — reserved subdomains that no tenant may claim.
# Grouped so we can add batches without disturbing the alphabetical
# ones. Lowercase; comparison is case-insensitive via normalize_slug.
RESERVED_SLUGS: Final[frozenset[str]] = frozenset({
    # Platform / brand surfaces
    "lms", "admin", "superadmin", "super-admin", "root",
    "demo",            # pinned to the current single-tenant data set
    "manasety", "manasety-school",
    # Operational / infra
    "api", "static", "assets", "cdn", "docs", "help", "support",
    "status", "health", "ping", "monitor", "metrics",
    "www", "mail", "smtp", "imap", "pop", "ftp", "ns", "ns1", "ns2",
    "mx", "dns", "whois",
    # Payment / sensitive flows
    "pay", "payments", "billing", "invoices", "wallet", "bank",
    # Auth / identity
    "auth", "login", "logout", "signin", "signup", "register",
    "oauth", "sso", "mfa", "otp",
    # Reserved for future app surfaces
    "app", "mobile", "web", "portal", "dashboard", "console",
    "control", "panel", "settings",
    # Marketing / public
    "home", "about", "blog", "news", "press", "legal", "terms",
    "privacy", "pricing", "sales",
})

# RFC 1035-flavoured label: lowercase letters/digits/hyphen, not
# starting or ending with a hyphen, 1-63 chars. The DB-side CHECK
# in the migration uses the same pattern.
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class SlugValidationError(ValueError):
    """Raised by validate_slug when the string isn't a usable slug.
    Carries a `reason` suitable for showing to an admin in Arabic."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize_slug(raw: str | None) -> str:
    """Lowercase + strip whitespace. Does not mutate otherwise — a
    pre-normalized slug round-trips, an invalid one still gets
    rejected by validate_slug."""
    return (raw or "").strip().lower()


def validate_slug(raw: str | None) -> str:
    """Return the normalized slug or raise SlugValidationError.

    Rules:
      - 1..63 characters total
      - [a-z0-9-] only, must start and end alphanumeric
      - not in RESERVED_SLUGS (checked case-insensitively via
        normalize_slug)
    """
    slug = normalize_slug(raw)
    if not slug:
        raise SlugValidationError("الاسم المختصر مطلوب.")
    if len(slug) > 63:
        raise SlugValidationError("الاسم المختصر طويل جدًا (حد أقصى 63 حرفًا).")
    if not _SLUG_RE.match(slug):
        raise SlugValidationError(
            "الاسم المختصر يسمح فقط بالحروف الصغيرة والأرقام والشرطة، "
            "ولا يبدأ ولا ينتهي بشرطة."
        )
    if slug in RESERVED_SLUGS:
        raise SlugValidationError(
            f"الاسم المختصر «{slug}» محجوز ولا يمكن استخدامه."
        )
    return slug


# Allowed values for schools.status — in sync with the migration's
# CHECK constraint. Keep this list as the single source of truth so
# a future lifecycle addition (e.g. `trial`) only edits one place.
SCHOOL_STATUSES: Final[tuple[str, ...]] = ("active", "suspended", "archived")

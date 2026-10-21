"""SAAS-003/004 (2026-10-12) — tenant identity + host resolution.

SAAS-003 lives at the top (slug validator + reserved list + status
enum) — SAAS-004 extends it with the request-time Host resolver,
the TenantContext ContextVar and the `before_request` hook that
drops onto `g.tenant` / `g.is_platform`.

Both halves share one module so slug rules and reserved labels
never drift between the model layer and the host middleware.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final, Iterator, Optional

from flask import (
    Flask, abort, current_app, g, redirect, request, url_for,
)


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
    # SAAS-023 — live subdomains on the shared server (nginx, 2026-10-20)
    "accountant", "chatwoot", "drporcelain", "easygo", "eg-uae", "lamma",
    "lexoffice", "marsoud", "n8n", "qafer", "whitemoon",
    # SAAS-023 — names Lamma (sister product) reserves (reserved-slugs.js)
    "almustashar", "activefit", "elyasmin", "qaffer", "sobou", "invitation",
    "landing", "media", "test", "preview", "contact", "faq", "school",
    "wedding", "birthday", "create",
    # SAAS-025 — platform console + remaining server hosts
    "console", "platform", "demo-admin", "elmouhamy", "qafr",
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


def validate_slug_format(raw: str | None) -> str:
    """Format-only check: shape + length + character set. Does NOT
    reject reserved slugs. Used by the host resolver (which must
    accept the already-provisioned `demo` tenant) and by any other
    code that only needs to confirm the slug could legally exist in
    the DB."""
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
    return slug


def validate_slug(raw: str | None) -> str:
    """Full validator — format AND reserved-list. Use at CREATION
    time (admin creates a new school) so no new tenant can claim a
    reserved subdomain. The existing `demo` tenant was provisioned
    before this list existed and is grandfathered via
    `validate_slug_format` in the resolver."""
    slug = validate_slug_format(raw)
    if slug in RESERVED_SLUGS:
        raise SlugValidationError(
            f"الاسم المختصر «{slug}» محجوز ولا يمكن استخدامه."
        )
    return slug


# Allowed values for schools.status — in sync with the migration's
# CHECK constraint. Keep this list as the single source of truth so
# a future lifecycle addition (e.g. `trial`) only edits one place.
SCHOOL_STATUSES: Final[tuple[str, ...]] = ("active", "suspended", "archived")


# ══════════════════════════════════════════════════════════════════════
# SAAS-004 (2026-10-12) — Host resolver + TenantContext
# ══════════════════════════════════════════════════════════════════════

# Modes:
#   off     — no behaviour change; g.tenant stays unset.
#   log     — resolver runs and logs would-be rejections, but never
#             blocks. Safe to turn on in production before DNS is
#             ready: nothing 404s / 403s, we just learn what *would*
#             happen under enforce.
#   enforce — resolver runs AND rejects unknown / suspended / malformed
#             hosts. The target state once DevOps lands wildcard DNS,
#             SSL and the server_name block.
TENANT_RESOLUTION_MODES: Final[tuple[str, ...]] = ("off", "log", "enforce")

# Only a-z, 0-9, dot and hyphen are allowed in a hostname label.
# Everything outside that set is a parse failure (which, under
# `enforce`, becomes a 404).
_HOST_SAFE_RE = re.compile(r"^[a-z0-9.\-]+$")

_log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Config helpers — pulled through current_app so tests can override
# ──────────────────────────────────────────────────────────────────────

def _cfg_mode() -> str:
    """Current resolution mode. Reads from Flask config, falls back
    to the TENANT_RESOLUTION_MODE env var, then to `off` so
    pre-existing code behaves exactly as before by default."""
    val = (current_app.config.get("TENANT_RESOLUTION_MODE")
           or os.environ.get("TENANT_RESOLUTION_MODE")
           or "off").strip().lower()
    return val if val in TENANT_RESOLUTION_MODES else "off"


def resolution_mode() -> str:
    """Public read of the effective TENANT_RESOLUTION_MODE."""
    return _cfg_mode()


def _cfg_base_domain() -> str:
    return (current_app.config.get("BASE_DOMAIN") or "").strip().lower()


def _cfg_platform_hosts() -> frozenset[str]:
    raw = current_app.config.get("PLATFORM_HOSTS") or ()
    return frozenset(h.strip().lower() for h in raw if h and h.strip())


def _cfg_legacy_hosts() -> dict[str, str]:
    """Map {legacy_host → slug}. Keeps the Flutter apps that bake
    an old host name working (e.g. lms.manasety.ai → demo)."""
    raw = current_app.config.get("LEGACY_HOSTS") or {}
    return {k.strip().lower(): v.strip().lower() for k, v in raw.items()}


# ──────────────────────────────────────────────────────────────────────
# Host normalisation
# ──────────────────────────────────────────────────────────────────────

def normalize_host(raw: str | None) -> str:
    """Lowercase, strip port, strip trailing dot, strip whitespace.

    Returns empty string for anything that would already fail parsing
    downstream — the caller treats that as "unknown host" per mode.
    An IPv6 literal (begins with `[`) returns empty because this
    product is served on hostnames, not literal IPs.
    """
    if not raw:
        return ""
    h = raw.strip().lower()
    if not h or h.startswith("["):
        return ""
    # Strip port.
    if ":" in h:
        host, _, port = h.rpartition(":")
        # If the "host" half is actually empty (:443 alone) or the
        # port half isn't numeric, the whole thing is garbage.
        if not host or not port.isdigit():
            return ""
        h = host
    # Strip trailing dot (FQDN form).
    if h.endswith("."):
        h = h[:-1]
    if not h or not _HOST_SAFE_RE.match(h):
        return ""
    return h


# ──────────────────────────────────────────────────────────────────────
# Resolver — returns a ResolvedTenant dataclass-ish namespace
# ──────────────────────────────────────────────────────────────────────

class ResolvedTenant:
    """What the resolver attaches to Flask's `g` object.

    Attributes:
      kind     — "tenant" | "platform" | "unknown" | "suspended" |
                 "blocked" | "malformed"
      school   — School row if kind == "tenant", else None
      slug     — resolved slug string (always set when kind == "tenant")
      host     — the normalized host we matched against
      reason   — short English code useful for logs / tests
      subscription — SAAS-027: the school's SubscriptionState (or None)
      support_bypass — SAAS-031 hook: a support session may see a
                 blocked school. Never set before SAAS-031.
    """

    __slots__ = ("kind", "school", "slug", "host", "reason", "subscription", "support_bypass")

    def __init__(self, kind: str, *, school=None, slug: str = "",
                 host: str = "", reason: str = "", subscription=None) -> None:
        self.kind = kind
        self.school = school
        self.slug = slug
        self.host = host
        self.reason = reason
        self.subscription = subscription
        self.support_bypass = False

    @property
    def read_only(self) -> bool:
        """Grace period: everything visible, nothing writable."""
        return self.kind == "tenant" and self.subscription is not None \
            and self.subscription.read_only

    @property
    def blocked(self) -> bool:
        """Suspended status or a subscription that doesn't allow access."""
        return self.kind in ("suspended", "blocked")

    @property
    def is_platform(self) -> bool:
        return self.kind == "platform"

    @property
    def ok(self) -> bool:
        return self.kind in ("tenant", "platform")


def resolve_host(host_header: str | None) -> ResolvedTenant:
    """Pure function: given a raw Host header, classify it.

    Does NOT read from `g` or `request`; the before_request wrapper
    does that. Separate so tests can hit it directly across hundreds
    of hostnames without spinning a test client."""
    host = normalize_host(host_header)
    if not host:
        return ResolvedTenant("malformed", host=host or "", reason="empty_or_bad_chars")

    # Platform first — matching one of PLATFORM_HOSTS short-circuits
    # before any lookup so the admin console doesn't need a schools row.
    if host in _cfg_platform_hosts():
        return ResolvedTenant("platform", host=host, reason="platform_host")

    # Legacy maps are explicit tenant aliases (e.g. lms.manasety.ai → demo).
    legacy = _cfg_legacy_hosts()
    if host in legacy:
        slug = legacy[host]
        return _resolve_by_slug(slug, host=host, reason="legacy_map")

    # Expect exactly `<slug>.<base>` — one subdomain level, nothing more.
    base = _cfg_base_domain()
    if base and host.endswith("." + base):
        label = host[: -(len(base) + 1)]
        # Multi-level (`a.b.manasety.ai`) and spoof-y (`demo.manasety.ai.evil.com`)
        # fall through here because the second check sees a dot inside `label`.
        if "." in label or not label:
            return ResolvedTenant("unknown", host=host, reason="non_single_label")
        return _resolve_by_slug(label, host=host, reason="subdomain")

    # Dev convenience: `*.localhost` acts like `*.<base>` so pytest
    # test clients and local browsers work without touching DNS.
    if host.endswith(".localhost"):
        label = host[: -len(".localhost")]
        if "." in label or not label:
            return ResolvedTenant("unknown", host=host, reason="non_single_label")
        return _resolve_by_slug(label, host=host, reason="dev_subdomain")

    # Bare `localhost` or anything else → unknown. Dev callers can
    # set TENANT_DEV_SLUG to force a tenant on a single-host setup.
    dev_slug = (current_app.config.get("TENANT_DEV_SLUG") or "").strip().lower()
    if dev_slug and host in ("localhost", "127.0.0.1"):
        return _resolve_by_slug(dev_slug, host=host, reason="dev_override")

    return ResolvedTenant("unknown", host=host, reason="no_match")


def _request_settings() -> dict:
    """Platform settings, read once per request (cached on g)."""
    from flask import has_app_context
    from .subscriptions import get_settings
    if has_app_context():
        cached = g.get("_platform_settings")
        if cached is None:
            cached = get_settings()
            g._platform_settings = cached
        return cached
    return get_settings()


def _moved_to(old_slug: str):
    """The school an old slug now belongs to, while its redirect window
    is open (archived schools never redirect)."""
    from datetime import datetime, timezone
    from ..extensions import db
    from ..models import School, SchoolSlugHistory
    h = SchoolSlugHistory.query.filter_by(old_slug=old_slug).first()
    if h is None:
        return None
    until = h.redirect_until if h.redirect_until.tzinfo else h.redirect_until.replace(tzinfo=timezone.utc)
    if until < datetime.now(timezone.utc):
        return None
    school = db.session.get(School, h.school_id)
    return school if school is not None and school.status != "archived" else None


def _resolve_by_slug(slug: str, *, host: str, reason: str) -> ResolvedTenant:
    """Look up the School row, enforce lifecycle status.
    Deferred import so this module stays importable before models load.

    Uses `validate_slug_format` not `validate_slug` — the latter
    would reject `demo` and any other reserved label that was
    grandfathered in before the reserved-list existed."""
    from ..models import School
    try:
        slug_norm = validate_slug_format(slug)
    except SlugValidationError:
        return ResolvedTenant("malformed", host=host, slug=slug,
                              reason=f"{reason}:bad_slug")
    school = School.query.filter_by(slug=slug_norm).first()
    if school is None:
        # SAAS-032 — a renamed school's old slug, inside its redirect window
        moved = _moved_to(slug_norm)
        if moved is not None:
            return ResolvedTenant("moved", host=host, slug=slug_norm, school=moved,
                                  reason=f"{reason}:moved")
        return ResolvedTenant("unknown", host=host, slug=slug_norm,
                              reason=f"{reason}:slug_not_found")
    # Fail-closed status check — only `active` passes. The ticket enum
    # is {active, suspended, archived}; a strict allow-list protects
    # us against future lifecycle values (`trial`, `pending`, …) that
    # land in the DB before the resolver learns about them, and
    # against row drift from a half-applied migration. Security review
    # (2026-10-12) flagged the previous blacklist as fail-open.
    if school.status == "active":
        # SAAS-027 — the subscription decides: trial / active → tenant,
        # grace → tenant + read_only, anything else → blocked. One
        # indexed read of the current subscription per request.
        from .subscriptions import current_subscription, effective_state, platform_today
        settings = _request_settings()
        state = effective_state(school, current_subscription(school.id),
                                platform_today(settings), settings)
        if state.blocked:
            return ResolvedTenant("blocked", host=host, slug=slug_norm, school=school,
                                  reason=f"{reason}:{state.state}", subscription=state)
        return ResolvedTenant("tenant", school=school, slug=slug_norm,
                              host=host, reason=reason, subscription=state)
    if school.status == "suspended":
        # Kept as its own kind (pre-SAAS-027 tests rely on it); enforced
        # exactly like "blocked" — see ResolvedTenant.blocked.
        from .subscriptions import SubscriptionState
        return ResolvedTenant("suspended", host=host, slug=slug_norm,
                              school=school, reason=f"{reason}:suspended",
                              subscription=SubscriptionState("suspended"))
    # archived — and any unexpected value — looks like unknown so we
    # never leak whether a slug exists in a non-active state.
    return ResolvedTenant("unknown", host=host, slug=slug_norm,
                          reason=f"{reason}:status_{school.status}")


# ──────────────────────────────────────────────────────────────────────
# TenantContext — ContextVar for jobs / CLI / cron
# ──────────────────────────────────────────────────────────────────────

_tenant_cv: ContextVar[Optional[int]] = ContextVar("manasety_tenant", default=None)


class TenantNotResolved(RuntimeError):
    """Raised when code asks for the current tenant and nothing is in
    scope (no request, no context manager)."""


@contextmanager
def tenant_context(school_id: int) -> Iterator[int]:
    """Scope `current_tenant_id()` to the given school for the duration
    of the with-block. Safe to nest; uses a ContextVar so concurrent
    threads / asyncio tasks don't leak into each other."""
    token = _tenant_cv.set(int(school_id))
    try:
        yield int(school_id)
    finally:
        _tenant_cv.reset(token)


def current_tenant() -> ResolvedTenant | None:
    """Return the ResolvedTenant attached by the before_request hook,
    or None if we're outside any request (jobs should use
    `current_tenant_id()` instead)."""
    return getattr(g, "tenant_resolved", None)


def current_tenant_id() -> int:
    """Return the current tenant's school_id — from the context var
    first (jobs), then from the resolved request tenant. Raises
    TenantNotResolved if neither is set."""
    cv = _tenant_cv.get()
    if cv is not None:
        return cv
    resolved = current_tenant()
    if resolved and resolved.kind == "tenant" and resolved.school is not None:
        return int(resolved.school.id)
    raise TenantNotResolved(
        "No tenant in scope. Wrap job/CLI code in "
        "`with tenant_context(school_id): ...`."
    )


def require_tenant() -> ResolvedTenant:
    """For view code that MUST have a tenant (not platform)."""
    r = current_tenant()
    if r is None or r.kind != "tenant":
        raise TenantNotResolved("Expected a tenant request, got none.")
    return r


# ──────────────────────────────────────────────────────────────────────
# SAAS-005 — single source of truth for `school_id`
# ──────────────────────────────────────────────────────────────────────

def current_school_id() -> int:
    """Return the active tenant's school_id — the ONE function every
    blueprint/service should call instead of reading
    `current_user.school_id` directly.

    Priority order:
      1. Explicit `tenant_context(school_id)` (jobs, CLI, cron workers).
      2. Host-resolved tenant (`g.tenant_resolved`) when the resolver
         is `log` or `enforce`.
      3. `g.api_user.school_id` — some mobile-API views stash the
         authenticated user there before this runs.
      4. `current_user.school_id` — legacy single-tenant fallback for
         `off` mode and dev DB. Preserves behaviour until wildcard
         DNS is live.

    Raises `TenantNotResolved` when none of the above have a tenant.
    That is intentionally strict — a view that reaches this helper
    with no tenant in scope was ambiguous before SAAS-005 too; now
    the ambiguity is loud instead of silent.
    """
    cv = _tenant_cv.get()
    if cv is not None:
        return int(cv)
    resolved = current_tenant()
    if resolved is not None and resolved.kind == "tenant" and resolved.school is not None:
        return int(resolved.school.id)
    # g.api_user — set by the mobile-API JWT middleware.
    api_user = getattr(g, "api_user", None)
    api_sid = getattr(api_user, "school_id", None) if api_user is not None else None
    if api_sid is not None:
        return int(api_sid)
    # current_user — Flask-Login's proxy. Importing lazily avoids
    # a module-import cycle during app factory wiring.
    try:
        from flask_login import current_user  # type: ignore
        if current_user and getattr(current_user, "is_authenticated", False):
            sid = getattr(current_user, "school_id", None)
            if sid is not None:
                return int(sid)
    except Exception:  # noqa: BLE001
        pass
    raise TenantNotResolved(
        "No tenant in scope — set tenant_context() for jobs or ensure "
        "the request resolved to a tenant / an authenticated user."
    )


# ──────────────────────────────────────────────────────────────────────
# Flask hook
# ──────────────────────────────────────────────────────────────────────

def init_app(app: Flask) -> None:
    """Register the before_request resolver on the Flask app. Call
    once from create_app()."""

    @app.before_request
    def _resolve_tenant_from_host():
        g.tenant_resolved = None
        g.tenant = None
        g.is_platform = False

        mode = _cfg_mode()
        if mode == "off":
            return None

        resolved = resolve_host(request.host)
        g.tenant_resolved = resolved
        g.tenant = resolved.school if resolved.kind == "tenant" else None
        g.is_platform = resolved.is_platform

        if mode == "log":
            # Record every rejection — ops uses this to confirm the
            # host set is complete before flipping to enforce.
            if not resolved.ok:
                _log.warning(
                    "tenancy[log] would reject host=%r kind=%s reason=%s",
                    request.host, resolved.kind, resolved.reason,
                )
            return None

        # enforce
        if resolved.kind == "moved":
            # SAAS-032 — old slug: 301 for web GETs, 410 school_moved for
            # the API (fixed mobile contract), 404 for anything else.
            base = current_app.config.get("BASE_DOMAIN") or "manasety.ai"
            new_host = f"{resolved.school.slug}.{base}"
            if request.path.startswith("/api/"):
                from flask import jsonify
                return jsonify({"error": "school_moved", "new_host": new_host}), 410
            if request.method in ("GET", "HEAD"):
                qs = request.query_string.decode("latin-1")
                return redirect(f"https://{new_host}{request.path}" + (f"?{qs}" if qs else ""), 301)
            abort(404)
        if request.path == "/_health":
            # SAAS-029 — nginx-sync's post-reload probe: 200 for any host
            # that resolved (incl. a blocked school), 404 otherwise.
            if resolved.kind in ("tenant", "platform", "suspended", "blocked"):
                g.tenant_health_ok = True
                return None
            abort(404)
        if resolved.kind == "tenant" or resolved.kind == "platform":
            return None
        if resolved.blocked:
            # SAAS-027 — suspended status or a subscription that doesn't
            # allow access: one page / one JSON shape, no login form.
            # SAAS-031 — except for platform support entering / inside a
            # live support session for this very school.
            # SAAS-037 — the app's "is this my school?" call explains the
            # block itself instead of getting a bare 403.
            if request.endpoint in ("api.public_school_info", "api.public_app_config"):
                return None
            # token-authenticated and cross-school: it skips blocked
            # schools itself (a blocked host must not stop every tick)
            if request.endpoint == "cron.tick":
                return None
            from .support_policy import bypass_for
            if request.endpoint == "support.enter" or bypass_for(resolved):
                resolved.support_bypass = True
                return None
            from .subscription_enforcement import blocked_response
            return blocked_response(resolved)
        # unknown / malformed / archived — never disclose which.
        if request.path.startswith("/api/public/"):
            # the probes of a slug-guesser count toward the same per-IP
            # limit as the hits (else the 404s are an unlimited oracle)
            from ..blueprints.api.public import rate_limited_response
            refused = rate_limited_response()
            if refused is not None:
                return refused
        abort(404)

    # ─── SAAS-006 — cross-tenant session kill ─────────────────────
    # Runs AFTER the resolver has stamped g.tenant. If a logged-in
    # user carries school_id != the host's tenant, drop them to the
    # login page on the current host instead of letting them see a
    # dashboard scoped to a tenant they don't belong to. Defence-in-
    # depth above the host-only cookie policy from D5.
    @app.before_request
    def _kill_cross_tenant_session():
        resolved = getattr(g, "tenant_resolved", None)
        if resolved is None or resolved.kind != "tenant" or resolved.school is None:
            return None
        try:
            from flask_login import current_user, logout_user
        except Exception:
            return None
        if not getattr(current_user, "is_authenticated", False):
            return None
        user_school_id = getattr(current_user, "school_id", None)
        if user_school_id is None:
            return None
        if int(user_school_id) == int(resolved.school.id):
            return None
        # Mismatch — tear down the session before any view sees it.
        app.logger.warning(
            "tenancy — dropped cross-tenant session: user_school=%s "
            "host_tenant=%s path=%s",
            user_school_id, resolved.school.id, request.path,
        )
        logout_user()
        # Preserve the attempted path only when it isn't the login
        # loop itself.
        if request.path != url_for("auth.login"):
            return redirect(url_for("auth.login"))
        return None

    # Expose on app for introspection (tests / debug).
    app.extensions.setdefault("manasety", {})["tenancy_installed"] = True

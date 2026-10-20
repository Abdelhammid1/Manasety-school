import os
from dotenv import load_dotenv

load_dotenv()


# ─── SAAS-001 (2026-10-12) ────────────────────────────────────────────
# APP_ENV decides which SECRET_KEY failures are fatal.  Values:
#   production  → fail boot when SECRET_KEY is missing, default, or <32 chars
#   development → allow a dev fallback (noisy warning via create_app)
#   testing     → silent fallback for pytest/CI
# A missing APP_ENV defaults to "production" because that is the safe
# default — any new deployment that forgets to set it fails fast
# instead of silently inheriting a known-weak key.
APP_ENV = os.environ.get("APP_ENV", "production").strip().lower()

_DEV_FALLBACK_SECRET = "dev-secret-change-me"
_MIN_SECRET_LEN = 32


def _resolve_secret_key() -> str:
    """Return a usable SECRET_KEY or raise RuntimeError.

    Production fails hard; dev/test fall back to the dev sentinel and
    create_app surfaces a WARNING so the operator sees it. The error
    message never prints the actual key value.
    """
    raw = os.environ.get("SECRET_KEY", "")
    key = (raw or "").strip()
    is_prod = APP_ENV not in ("development", "testing")
    weak = (
        not key
        or key == _DEV_FALLBACK_SECRET
        or len(key) < _MIN_SECRET_LEN
    )
    if is_prod and weak:
        raise RuntimeError(
            "SECRET_KEY is missing, default, or shorter than "
            f"{_MIN_SECRET_LEN} characters in APP_ENV={APP_ENV!r}. "
            "Generate one with `python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\"` and set it in the "
            "service environment file. (Value not shown.)"
        )
    return key or _DEV_FALLBACK_SECRET


# ─── SAAS-007 (2026-10-12) ────────────────────────────────────────────
# JWT_SIGNING_KEY is a SEPARATE secret from SECRET_KEY so a leak of
# one credential doesn't compromise both the web session and the
# mobile API at once. If unset, fall back to SECRET_KEY so single-
# server dev continues to work — production refuses to boot with the
# fallback, same policy as SECRET_KEY.
_DEV_FALLBACK_JWT = "dev-jwt-change-me"


def _resolve_jwt_signing_key(session_key: str) -> str:
    raw = os.environ.get("JWT_SIGNING_KEY", "")
    key = (raw or "").strip()
    is_prod = APP_ENV not in ("development", "testing")
    weak_or_shared = (
        not key
        or key == _DEV_FALLBACK_JWT
        or len(key) < _MIN_SECRET_LEN
        or key == session_key
    )
    if is_prod and weak_or_shared:
        raise RuntimeError(
            "JWT_SIGNING_KEY is missing, default, shorter than "
            f"{_MIN_SECRET_LEN} characters, or identical to SECRET_KEY "
            f"in APP_ENV={APP_ENV!r}. Mint a distinct value: `python -c "
            "\"import secrets; print(secrets.token_urlsafe(48))\"` "
            "and set JWT_SIGNING_KEY in the service environment file. "
            "A separate key means a leak of one credential does not "
            "compromise both the web session and the mobile API."
        )
    # Dev fallback: reuse SECRET_KEY if unset. One-server loopback-only
    # setups don't need the split; the production gate above makes sure
    # a real deployment can't ship with that fallback.
    return key or session_key


# ─── SAAS-024 — tenancy hosts from the environment ──────────────────
# Unset → the historical defaults. Set but empty → none (e.g.
# PLATFORM_HOSTS= turns lms.manasety.ai back into a normal host).
# Anything malformed refuses to boot: a typo here would silently route
# a school's traffic to the wrong tenant or 404 it.
_DEFAULT_BASE_DOMAIN = "manasety.ai"
_DEFAULT_PLATFORM_HOSTS = "lms.manasety.ai"
_DEFAULT_LEGACY_HOSTS = "school.manasety.ai=demo"


def _env_host(raw: str, var: str) -> str:
    from .services.tenancy import normalize_host
    want = (raw or "").strip().lower().rstrip(".")
    host = normalize_host(raw)
    if not host or host != want:
        raise RuntimeError(
            f"{var}: {raw!r} is not a valid host name (letters, digits, "
            "dots and hyphens only; no port, no scheme)."
        )
    return host


def _resolve_base_domain(environ=os.environ) -> str:
    raw = environ.get("BASE_DOMAIN")
    return _env_host(_DEFAULT_BASE_DOMAIN if raw is None else raw, "BASE_DOMAIN")


def _resolve_platform_hosts(environ=os.environ) -> list[str]:
    raw = environ.get("PLATFORM_HOSTS")
    raw = _DEFAULT_PLATFORM_HOSTS if raw is None else raw
    return [_env_host(h, "PLATFORM_HOSTS") for h in raw.split(",") if h.strip()]


def _resolve_legacy_hosts(environ=os.environ) -> dict[str, str]:
    from .services.tenancy import SlugValidationError, validate_slug_format
    raw = environ.get("LEGACY_HOSTS")
    raw = _DEFAULT_LEGACY_HOSTS if raw is None else raw
    out: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        host, sep, slug = item.partition("=")
        if not sep:
            raise RuntimeError(
                f"LEGACY_HOSTS: entry {item!r} must look like host=slug "
                "(comma-separated, e.g. school.manasety.ai=demo)."
            )
        host = _env_host(host, "LEGACY_HOSTS")
        try:
            out[host] = validate_slug_format(slug)
        except SlugValidationError:
            raise RuntimeError(f"LEGACY_HOSTS: {slug!r} (for {host}) is not a valid slug.")
    return out


def _resolve_tenancy_hosts(environ=os.environ):
    base = _resolve_base_domain(environ)
    platform = _resolve_platform_hosts(environ)
    legacy = _resolve_legacy_hosts(environ)
    both = sorted(set(platform) & set(legacy))
    if both:
        raise RuntimeError(
            f"{both} listed in both PLATFORM_HOSTS and LEGACY_HOSTS — a host "
            "is either the platform console or a school alias, not both."
        )
    return base, platform, legacy


class Config:
    SECRET_KEY = _resolve_secret_key()
    # SAAS-007 — mobile-API JWTs sign with a DIFFERENT key than the
    # web session cookie so a leak of either credential doesn't
    # compromise both. Resolved AFTER SECRET_KEY so the equality
    # check can reject shared values.
    JWT_SIGNING_KEY = _resolve_jwt_signing_key(SECRET_KEY)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://manasety:manasety@localhost:5432/manasety_lms"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOCKOUT_MAX_ATTEMPTS = int(os.environ.get("LOCKOUT_MAX_ATTEMPTS", "5"))
    LOCKOUT_MINUTES = int(os.environ.get("LOCKOUT_MINUTES", "15"))
    DEFAULT_SCHOOL_NAME = os.environ.get(
        "DEFAULT_SCHOOL_NAME", "مدرستي"
    )
    DEFAULT_SCHOOL_CODE = os.environ.get("DEFAULT_SCHOOL_CODE", "SCH")
    WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "stub")
    LANGUAGES = ["ar"]
    DEFAULT_LANGUAGE = "ar"
    # Sprint 10 Phase 2 — cap uploaded material file size at 10 MB
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    # Sprint 10 Phase 3 — Firebase Cloud Messaging service-account path (optional)
    FCM_SERVICE_ACCOUNT_PATH = os.environ.get("FCM_SERVICE_ACCOUNT_PATH")
    # Ticket "Additional 3" — token protecting the /cron/tick endpoint
    # that flips overdue invoices + sends payment reminders daily.
    CRON_TOKEN = os.environ.get("CRON_TOKEN", "dev-cron-token-change-me")
    BASE_DOMAIN, PLATFORM_HOSTS, LEGACY_HOSTS = _resolve_tenancy_hosts()

    # ─── SAAS-001 (2026-10-12) — explicit session cookie flags ────
    # Hard-coded here (not read from env) so a prod deployment can't
    # accidentally weaken them. SESSION_COOKIE_DOMAIN and SERVER_NAME
    # are deliberately NOT set — decision D5 keeps cookies host-only
    # so a subdomain's cookie can't leak to its siblings.
    SESSION_COOKIE_HTTPONLY  = True
    SESSION_COOKIE_SAMESITE  = "Lax"
    SESSION_COOKIE_SECURE    = APP_ENV not in ("development", "testing")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE   = APP_ENV not in ("development", "testing")
    # SESSION_COOKIE_DOMAIN and SERVER_NAME intentionally OMITTED (D5).

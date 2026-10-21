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


# ─── SAAS-010 — CRON_TOKEN gets the SECRET_KEY policy ───────────────
_DEV_CRON_TOKEN = "dev-cron-token-change-me"


def _resolve_cron_token(environ=os.environ, app_env=None) -> str:
    app_env = APP_ENV if app_env is None else app_env
    key = (environ.get("CRON_TOKEN") or "").strip()
    is_prod = app_env not in ("development", "testing")
    if is_prod and (not key or key == _DEV_CRON_TOKEN or len(key) < _MIN_SECRET_LEN):
        raise RuntimeError(
            "CRON_TOKEN is missing, default, or shorter than "
            f"{_MIN_SECRET_LEN} characters in APP_ENV={app_env!r}. Mint one "
            "with `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`. "
            "(Value not shown.)"
        )
    return key or _DEV_CRON_TOKEN


# ─── SAAS-025 — platform (Super Admin) secrets ──────────────────────

def _resolve_platform_enc_key(session_key: str, environ=os.environ, app_env=None) -> str:
    """Key that encrypts platform TOTP secrets. Same policy as
    JWT_SIGNING_KEY: required and >= 32 chars in production, distinct
    from SECRET_KEY. The value is never printed."""
    app_env = APP_ENV if app_env is None else app_env
    key = (environ.get("PLATFORM_ENC_KEY") or "").strip()
    is_prod = app_env not in ("development", "testing")
    if is_prod and (not key or len(key) < _MIN_SECRET_LEN or key == session_key):
        raise RuntimeError(
            "PLATFORM_ENC_KEY is missing, shorter than "
            f"{_MIN_SECRET_LEN} characters, or identical to SECRET_KEY in "
            f"APP_ENV={app_env!r}. Mint one with `python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\"`. (Value not shown.)"
        )
    return key or f"dev-platform-key|{session_key}"


def _resolve_support_session_key(session_key: str, environ=os.environ, app_env=None) -> str:
    """SAAS-031 — signs the 60-second console → school hand-off token.
    Same policy as JWT_SIGNING_KEY (required, >= 32 chars, != SECRET_KEY
    in production). The value is never printed."""
    app_env = APP_ENV if app_env is None else app_env
    key = (environ.get("SUPPORT_SESSION_KEY") or "").strip()
    is_prod = app_env not in ("development", "testing")
    if is_prod and (not key or len(key) < _MIN_SECRET_LEN or key == session_key):
        raise RuntimeError(
            "SUPPORT_SESSION_KEY is missing, shorter than "
            f"{_MIN_SECRET_LEN} characters, or identical to SECRET_KEY in "
            f"APP_ENV={app_env!r}. Mint one with `python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\"`. (Value not shown.)"
        )
    return key or f"dev-support-key|{session_key}"


def _env_int(name: str, default: int, environ=os.environ) -> int:
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) <= 0:
        raise RuntimeError(f"{name} must be a positive integer (got {raw!r}).")
    return int(raw)


# ─── SAAS-024 — tenancy hosts from the environment ──────────────────
# Unset → the historical defaults. Set but empty → none (e.g.
# PLATFORM_HOSTS= turns lms.manasety.ai back into a normal host).
# Anything malformed refuses to boot: a typo here would silently route
# a school's traffic to the wrong tenant or 404 it.
_DEFAULT_BASE_DOMAIN = "manasety.ai"
_DEFAULT_PLATFORM_HOSTS = "console.manasety.ai"
_DEFAULT_LEGACY_HOSTS = ""


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
                "(comma-separated, e.g. lms.manasety.ai=demo)."
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
    CRON_TOKEN = _resolve_cron_token()
    # SAAS-011 — uploaded files, outside app/static. Default: instance/uploads.
    UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT") or None
    # SAAS-009 — trust nginx's X-Forwarded-For / -Proto. Off by default:
    # only turn on once gunicorn's port is unreachable from outside,
    # otherwise any client could forge its IP.
    TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "").strip().lower() in (
        "1", "true", "yes", "on")
    BASE_DOMAIN, PLATFORM_HOSTS, LEGACY_HOSTS = _resolve_tenancy_hosts()
    # SAAS-025 — platform console session + secrets.
    PLATFORM_ENC_KEY = _resolve_platform_enc_key(SECRET_KEY)
    SUPPORT_SESSION_KEY = _resolve_support_session_key(SECRET_KEY)
    PLATFORM_SESSION_MINUTES = _env_int("PLATFORM_SESSION_MINUTES", 30)
    PLATFORM_SESSION_MAX_HOURS = 8
    PLATFORM_SESSION_COOKIE_NAME = "manasety_platform"
    # SAAS-029 — nginx-sync (server-side CLI only; the web app never reads
    # these paths or runs docker). Defaults match the production layout.
    NGINX_CONF_DIR = os.environ.get("NGINX_CONF_DIR") or "/opt/manasety/nginx"
    NGINX_BACKUP_ROOT = os.environ.get("NGINX_BACKUP_ROOT") or "/opt/manasety"
    NGINX_CONTAINER = os.environ.get("NGINX_CONTAINER") or "manasety-nginx-1"
    NGINX_WILDCARD_CERT = os.environ.get("NGINX_WILDCARD_CERT") or "wildcard-manasety"
    NGINX_CERT_DIR = os.environ.get("NGINX_CERT_DIR") or "/etc/letsencrypt/live"
    NGINX_CERT_FILE = os.environ.get("NGINX_CERT_FILE") or         "/opt/manasety/certbot/conf/live/wildcard-manasety/fullchain.pem"
    NGINX_UPSTREAM = os.environ.get("NGINX_UPSTREAM") or "172.21.0.1:5006"

    # SAAS-033 — platform notices (billing / expiry). Off unless enabled;
    # outside production only the allow-list ever receives anything.
    PLATFORM_EMAILS_ENABLED = (os.environ.get("PLATFORM_EMAILS_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on")
    PLATFORM_EMAIL_ALLOWLIST = (
        None if APP_ENV not in ("development", "testing") and not os.environ.get("PLATFORM_EMAIL_ALLOWLIST")
        else frozenset(a.strip().lower() for a in (os.environ.get("PLATFORM_EMAIL_ALLOWLIST") or "").split(",")
                       if a.strip()))

    # SAAS-027 — second line of the read-only (grace) enforcement: a write
    # reaching the DB through a GET route. "log" reports only (default);
    # "enforce" refuses the flush. Anything else is treated as "log".
    # SAAS-028 — platform outbound mail (setup links, billing notices).
    # Unset host or from = not configured: links are shown on screen only.
    PLATFORM_SMTP_HOST = (os.environ.get("PLATFORM_SMTP_HOST") or "").strip()
    PLATFORM_SMTP_PORT = _env_int("PLATFORM_SMTP_PORT", 587)
    PLATFORM_SMTP_USERNAME = (os.environ.get("PLATFORM_SMTP_USERNAME") or "").strip()
    PLATFORM_SMTP_PASSWORD = os.environ.get("PLATFORM_SMTP_PASSWORD") or ""
    PLATFORM_SMTP_FROM = (os.environ.get("PLATFORM_SMTP_FROM") or "").strip()
    PLATFORM_SMTP_TLS = (os.environ.get("PLATFORM_SMTP_TLS") or "1").strip().lower() not in (
        "0", "false", "no", "off")
    SUBSCRIPTION_RO_FLUSH_GUARD = (os.environ.get("SUBSCRIPTION_RO_FLUSH_GUARD") or "log").strip().lower()

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

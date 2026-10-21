"""SAAS-042 — post-deploy smoke check. Read-only: GETs, plus the login
POST of the known test-school accounts (SAAS-041). Every check prints
PASS / FAIL with its time; any FAIL → non-zero exit.

The HTTP layer is a small `Transport` so the CLI uses real HTTPS
(stdlib only — nothing new to install on the server) and the tests drive
the same checks through the Flask test client.
"""
from __future__ import annotations

import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

ROLES = ("admin", "teacher", "student", "parent")
CERT_MIN_DAYS = 14


@dataclass
class Resp:
    status: int
    url: str            # final URL after redirects
    body: str
    headers: dict


@dataclass
class Result:
    name: str
    ok: bool
    ms: int
    detail: str = ""


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)


class Transport:
    """Real HTTP(S): one cookie jar per session, redirects followed."""

    def __init__(self, timeout: float = 15):
        self.timeout = timeout

    def session(self):
        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar), HTTPRedirectHandler())

        def fetch(method, url, data=None, headers=None) -> Resp:
            body = urlencode(data).encode() if data is not None else None
            req = Request(url, data=body, method=method, headers={"User-Agent": "manasety-smoke/1",
                                                                     **(headers or {})})
            try:
                with opener.open(req, timeout=self.timeout) as r:
                    return Resp(r.status, r.url, r.read().decode("utf-8", "replace"), dict(r.headers))
            except HTTPError as e:
                return Resp(e.code, e.url or url, e.read().decode("utf-8", "replace"), dict(e.headers))
        return fetch

    def cert_days_left(self, host: str) -> int:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=self.timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                not_after = str((tls.getpeercert() or {})["notAfter"])
        end = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        return (end - datetime.now(timezone.utc)).days


def read_accounts(path) -> dict[str, dict[str, tuple[str, str]]]:
    """The file seed-test-schools writes: {slug: {role: (user, password)}}."""
    out, cur = {}, None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\[(test-[ab])\]", line)
        if m:
            cur = out.setdefault(m.group(1), {})
            continue
        m = re.match(r"\s+(admin|teacher|student|parent)\s+(\S+)\s+(\S+)\s*$", line)
        if m and cur is not None:
            cur[m.group(1)] = (m.group(2), m.group(3))
    return out


def _timed(report: Report, name: str, fn) -> None:
    t = time.monotonic()
    try:
        ok, detail = fn()
    except (URLError, OSError, ssl.SSLError, ValueError, KeyError) as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    report.results.append(Result(name, bool(ok), int((time.monotonic() - t) * 1000), detail))


def _csrf(body: str) -> str | None:
    m = re.search(r'name="csrf_token" value="([^"]+)"', body)
    return m.group(1) if m else None


def run(*, base_url: str, console_url: str, school_url: str | None, accounts: dict | None,
        transport, check_cert: bool = True) -> Report:
    rep = Report()
    fetch = transport.session()

    def home():
        r = fetch("GET", base_url.rstrip("/") + "/")
        return r.status == 200, f"{r.status} {r.url}"
    _timed(rep, f"home {base_url}", home)

    def console():
        r = transport.session()("GET", console_url.rstrip("/") + "/superadmin/login")
        return r.status == 200 and 'name="password"' in r.body, f"{r.status}"
    _timed(rep, f"console login page {console_url}", console)

    if school_url:
        def health():
            r = transport.session()("GET", school_url.rstrip("/") + "/_health")
            return r.status == 200, f"{r.status}"
        _timed(rep, f"health {school_url}", health)

        creds = (accounts or {}).get((urlsplit(school_url).hostname or "").split(".")[0], {})
        for role in ROLES:
            if role not in creds:
                rep.results.append(Result(f"login {role}", False, 0, "no account in the accounts file"))
                continue
            user, pw = creds[role]

            def login(user=user, pw=pw):
                s = transport.session()
                login_url = school_url.rstrip("/") + "/auth/login"
                page = s("GET", login_url)
                token = _csrf(page.body)
                if page.status != 200 or not token:
                    return False, f"login page {page.status}"
                # the browser sends a same-origin Referer (Referrer-Policy same-origin)
                r = s("POST", login_url, {"csrf_token": token, "username": user, "password": pw},
                      {"Referer": login_url})
                landed = urlsplit(r.url).path
                if r.status != 200 or landed.startswith("/auth/login"):
                    return False, f"{r.status} landed on {landed}"
                return True, f"home page {landed}"
            _timed(rep, f"login {role} + home page", login)

    if check_cert:
        for url in {base_url, console_url} | ({school_url} if school_url else set()):
            host = urlsplit(url).hostname

            def cert(host=host):
                days = transport.cert_days_left(host)
                return days > CERT_MIN_DAYS, f"{days} day(s) left"
            _timed(rep, f"certificate {host} > {CERT_MIN_DAYS} days", cert)
    return rep

"""SAAS-029 — nginx-sync: golden template, conflicts, rollback, idempotence,
queue dedupe, --only, /_health, and "no docker from the web process".
No real docker: every external command goes through a fake Runner."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from isolation_harness import host

FIXTURES = Path(__file__).parent / "fixtures" / "nginx"
ROOT = Path(__file__).resolve().parents[1]


class FakeRunner:
    """Records calls; behaviour switches per test."""

    def __init__(self, dump=None, test_rc=0, reload_rc=0, healthy=True, cert_days=200,
                 cert_rc=0):
        self.calls: list[str] = []
        self.dump = dump if dump is not None else (FIXTURES / "nginx_T_clean.txt").read_text(encoding="utf-8")
        self.test_rc, self.reload_rc, self.healthy = test_rc, reload_rc, healthy
        self.cert_days, self.cert_rc = cert_days, cert_rc

    def nginx_test(self):
        self.calls.append("test")
        rc = self.test_rc if isinstance(self.test_rc, int) else self.test_rc.pop(0)
        return rc, "nginx: configuration file test failed" if rc else "syntax is ok"

    def nginx_dump(self):
        self.calls.append("dump")
        return 0, self.dump

    def nginx_reload(self):
        self.calls.append("reload")
        return self.reload_rc, ""

    def health(self, h):
        self.calls.append(f"health:{h}")
        return (0, '{"ok": true}\n200') if self.healthy else (0, "<html>\n502")

    def cert_enddate(self, path):
        end = datetime.now(timezone.utc) + timedelta(days=self.cert_days, hours=1)
        return self.cert_rc, "notAfter=" + end.strftime("%b %d %H:%M:%S %Y GMT")


@pytest.fixture
def st(app, tmp_path):
    from app.services.nginx_sync import Settings
    conf = tmp_path / "nginx"
    conf.mkdir()
    return Settings(conf_dir=conf, backup_root=tmp_path, container="manasety-nginx-1",
                    cert="wildcard-manasety", cert_dir="/etc/letsencrypt/live",
                    cert_file="/x/fullchain.pem", upstream="172.21.0.1:5006",
                    base_domain="manasety.ai")


def _sync(app, st, runner, **kw):
    from app.services.nginx_sync import run_sync
    with app.app_context():
        return run_sync(runner=runner, st=st, **kw)


def test_golden_block(app, st):
    from app.services.nginx_sync import render_block
    with app.app_context():
        out = render_block(st, "demo")
    assert out == (FIXTURES / "demo_block.golden.conf").read_text(encoding="utf-8")


def test_generated_file_header_order_and_statuses(app, st, two_schools):
    from app.services.nginx_sync import GENERATED_HEADER, render_file
    with app.app_context():
        text = render_file(st)
    assert text.startswith(GENERATED_HEADER + "\n")
    slugs = re.findall(r"^# school: (\S+)$", text, re.M)
    assert slugs == sorted(slugs)
    assert {"alpha", "beta"} <= set(slugs)


def test_archived_school_has_no_block_suspended_does(app, st, two_schools):
    from app.extensions import db
    from app.models import School
    from app.services.nginx_sync import render_file
    A, B = two_schools["A"]["school"].id, two_schools["B"]["school"].id
    with app.app_context():
        db.session.get(School, A).status = "archived"
        db.session.get(School, B).status = "suspended"
        db.session.commit()
        text = render_file(st)
        db.session.get(School, A).status = "active"
        db.session.get(School, B).status = "active"
        db.session.commit()
        db.session.remove()
    assert "# school: alpha" not in text and "# school: beta" in text


def test_bad_slug_in_db_never_reaches_nginx(app, st, monkeypatch):
    from app.services import nginx_sync
    monkeypatch.setattr(nginx_sync, "wanted_slugs",
                        lambda: [nginx_sync._checked_slug("evil;\n} server {")])
    with app.app_context(), pytest.raises(nginx_sync.SyncError):
        nginx_sync.render_file(st)


def test_apply_then_second_run_is_unchanged(app, st, two_schools):
    r1 = FakeRunner()
    res = _sync(app, st, r1)
    assert res.status == "applied", res.log
    assert r1.calls[:3] == ["dump", "test", "reload"]
    assert "health:alpha.manasety.ai" in r1.calls
    assert list(st.backup_root.glob("nginx.bak_*/schools.conf"))
    r2 = FakeRunner()
    res2 = _sync(app, st, r2)
    assert res2.status == "unchanged" and "reload" not in r2.calls


def test_nginx_t_failure_restores_and_never_reloads(app, st, two_schools):
    st.target.write_text("# old file\n", encoding="utf-8")
    r = FakeRunner(test_rc=1)
    res = _sync(app, st, r)
    assert res.status == "failed" and "test failed" in "\n".join(res.log)
    assert st.target.read_text(encoding="utf-8") == "# old file\n"
    assert "reload" not in r.calls
    assert not (st.conf_dir / "schools.conf.new").exists()


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """The probe's pauses are recorded, not slept."""
    from app.services import nginx_sync
    slept = []
    monkeypatch.setattr(nginx_sync, "_sleep", slept.append)
    return slept


class SlowWorkersRunner(FakeRunner):
    """/_health answers the old worker's HTML `html_first` times per host,
    then the app's JSON (nginx workers still starting after a reload)."""

    def __init__(self, html_first, **kw):
        super().__init__(**kw)
        self.html_first, self.seen = html_first, {}

    def health(self, h):
        self.calls.append(f"health:{h}")
        n = self.seen[h] = self.seen.get(h, 0) + 1
        return (0, "<html>Lamma</html>\n200") if n <= self.html_first else (0, '{"ok": true}\n200')


def test_probe_retries_until_the_new_workers_answer(app, st, two_schools, _no_real_sleep):
    """Two HTML answers (old worker), then JSON: applied, no rollback."""
    from app.services import nginx_sync
    st.target.write_text("# old file\n", encoding="utf-8")
    r = SlowWorkersRunner(html_first=2)
    res = _sync(app, st, r)
    assert res.status == "applied", res.log
    assert r.calls.count("reload") == 1
    assert all(n == 3 for n in r.seen.values()) and r.seen
    assert _no_real_sleep == [nginx_sync.PROBE_DELAY] * (2 * len(r.seen))


def test_probe_rolls_back_only_after_every_attempt_fails(app, st, two_schools, _no_real_sleep):
    from app.services import nginx_sync
    st.target.write_text("# old file\n", encoding="utf-8")
    r = SlowWorkersRunner(html_first=99)
    res = _sync(app, st, r)
    assert res.status == "failed"
    assert st.target.read_text(encoding="utf-8") == "# old file\n"
    assert r.calls.count("reload") == 2
    first = next(iter(r.seen))
    assert r.seen[first] == nginx_sync.PROBE_ATTEMPTS
    # bounded: attempts x per-try timeout + pauses
    assert nginx_sync.PROBE_ATTEMPTS * nginx_sync.PROBE_TIMEOUT +         (nginx_sync.PROBE_ATTEMPTS - 1) * nginx_sync.PROBE_DELAY <= 30


def test_verification_failure_rolls_back(app, st, two_schools):
    st.target.write_text("# old file\n", encoding="utf-8")
    r = FakeRunner(healthy=False)
    res = _sync(app, st, r)
    assert res.status == "failed"
    assert st.target.read_text(encoding="utf-8") == "# old file\n"
    assert r.calls.count("reload") == 2           # apply, then rollback reload


def test_name_conflict_refused(app, st, two_schools):
    from app.extensions import db
    from app.models import School
    A = two_schools["A"]["school"].id
    dump = (FIXTURES / "nginx_T_conflict.txt").read_text(encoding="utf-8")
    with app.app_context():
        # bypass RESERVED_SLUGS on purpose: this is the second line of defence
        db.session.get(School, A).slug = "accountant"
        db.session.commit()
    try:
        r = FakeRunner(dump=dump)
        res = _sync(app, st, r)
        assert res.status == "failed"
        assert "accountant.manasety.ai" in "\n".join(res.log)
        assert not st.target.exists() and "reload" not in r.calls
    finally:
        with app.app_context():
            db.session.get(School, A).slug = "alpha"
            db.session.commit()
            db.session.remove()


def test_wildcard_and_schools_conf_names_are_not_conflicts():
    from app.services.nginx_sync import foreign_server_names
    dump = (FIXTURES / "nginx_T_clean.txt").read_text(encoding="utf-8")
    names = foreign_server_names(dump)
    assert "demo.manasety.ai" not in names          # lives in schools.conf
    assert not any(n.startswith("*") for n in names)
    assert "chatwoot.manasety.ai" in names


def test_check_and_dry_run_write_nothing(app, st, two_schools):
    r = FakeRunner()
    res = _sync(app, st, r, check=True)
    assert res.status == "check" and "+# school: alpha" in res.diff
    res = _sync(app, st, r, dry_run=True)
    assert res.status == "dry_run"
    assert not st.target.exists() and "reload" not in r.calls


def test_only_touches_one_slug(app, st, two_schools):
    old = "# GENERATED by nginx-sync — do not edit\n\n# school: beta\nKEEP-ME\n# end school: beta\n"
    st.target.write_text(old, encoding="utf-8")
    r = FakeRunner()
    res = _sync(app, st, r, only="alpha")
    assert res.status == "applied", res.log
    text = st.target.read_text(encoding="utf-8")
    assert "KEEP-ME" in text and "# school: alpha" in text
    assert res.changed_hosts == ["alpha.manasety.ai"]


def test_cert_warning_and_unreadable_cert(app, st, two_schools):
    res = _sync(app, st, FakeRunner(cert_days=10), check=True)
    assert res.cert_days_left == 10 and res.warnings
    res = _sync(app, st, FakeRunner(cert_rc=1))
    assert res.status == "applied" and res.cert_days_left is None and res.warnings


def test_runner_refuses_other_commands():
    from app.services.nginx_sync import Runner, SyncError
    r = Runner("manasety-nginx-1")
    for argv in (["docker", "restart", "manasety-nginx-1"], ["systemctl", "reload", "nginx"],
                 ["docker", "exec", "manasety-nginx-1", "sh", "-c", "rm -rf /"]):
        with pytest.raises(SyncError):
            r.run(argv)


# ─── queue ──────────────────────────────────────────────────────────

@pytest.fixture
def clean_jobs(app):
    from app.extensions import db
    from app.models import PlatformJob
    with app.app_context():
        PlatformJob.query.delete()
        db.session.commit()
    yield
    with app.app_context():
        PlatformJob.query.delete()
        db.session.commit()
        db.session.remove()


def test_queue_dedupes_and_from_queue_applies(app, st, two_schools, clean_jobs):
    from app.extensions import db
    from app.models import PlatformJob
    from app.services.nginx_queue import request_nginx_sync, school_subdomain_status
    from app.services.nginx_sync import run_queue
    A = two_schools["A"]["school"].id
    with app.app_context():
        j1 = request_nginx_sync("school_created", school_id=A)
        j2 = request_nginx_sync("sync_now")
        db.session.commit()
        assert j1.id == j2.id and PlatformJob.query.count() == 1
        assert school_subdomain_status(A) == "queued"
        res = run_queue(runner=FakeRunner(), st=st)
        assert res.status == "applied"
        job = db.session.get(PlatformJob, j1.id)
        assert job.status == "succeeded" and "alpha" in job.result["slugs"]
        assert school_subdomain_status(A) == "active"
        assert run_queue(runner=FakeRunner(), st=st) is None     # nothing pending
        db.session.remove()


def test_failed_job_recorded_with_redacted_log(app, st, two_schools, clean_jobs):
    from app.extensions import db
    from app.models import PlatformJob
    from app.services.nginx_queue import request_nginx_sync, school_subdomain_status
    from app.services.nginx_sync import run_queue
    with app.app_context():
        request_nginx_sync("x")
        db.session.commit()
        run_queue(runner=FakeRunner(test_rc=1), st=st)
        job = PlatformJob.query.one()
        assert job.status == "failed" and "nginx -t" in job.log
        assert school_subdomain_status(two_schools["A"]["school"].id) == "failed"
        db.session.remove()


# ─── /_health ───────────────────────────────────────────────────────

def test_health_route(app, two_schools, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    c = app.test_client()
    r = c.get("/_health", base_url=host(two_schools["A"]))
    assert r.status_code == 200 and r.json == {"ok": True}
    assert c.get("/_health", base_url="http://ghost-tenant.manasety.ai").status_code == 404


def test_health_works_for_suspended_school(app, two_schools, monkeypatch):
    from app.extensions import db
    from app.models import School
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    A = two_schools["A"]["school"].id
    with app.app_context():
        db.session.get(School, A).status = "suspended"
        db.session.commit()
    try:
        r = app.test_client().get("/_health", base_url=host(two_schools["A"]))
        assert r.status_code == 200 and r.json == {"ok": True}
    finally:
        with app.app_context():
            db.session.get(School, A).status = "active"
            db.session.commit()
            db.session.remove()


# ─── static: the web process never runs docker ───────────────────────

def test_no_docker_or_subprocess_outside_nginx_sync():
    offenders = []
    for p in (ROOT / "app").rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        # SAAS-050: system-restore (server CLI only) runs psql to load a dump
        if rel in ("app/services/nginx_sync.py", "app/services/system_restore.py"):
            continue
        text = p.read_text(encoding="utf-8")
        if re.search(r"\bsubprocess\b|os\.system|os\.popen|[\"']docker[\"']", text):
            offenders.append(rel)
    assert not offenders, offenders


def test_nginx_sync_only_imported_by_the_cli():
    importers = []
    for p in (ROOT / "app").rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel in ("app/services/nginx_sync.py",):
            continue
        # \bnginx_sync\b: the module itself, not request_nginx_sync & co.
        if re.search(r"^\s*(from\s+[.\w]*\bnginx_sync\b|from\s+[.\w]+\s+import\s+.*\bnginx_sync\b"
                     r"|import\s+[.\w]*\bnginx_sync\b)", p.read_text(encoding="utf-8"), re.M):
            importers.append(rel)
    assert importers == ["app/blueprints/superadmin/cli.py"], importers


# ─── SAAS-040 ───────────────────────────────────────────────────────────

def test_sync_never_touches_files_it_did_not_generate(app, st, two_schools):
    """Lamma's wildcard and every other conf in the folder stay byte-for-byte."""
    import os
    others = {"wildcard-lamma.conf": "server { server_name *.manasety.ai; }\n",
              "lms.conf": "# hand-written\n", "console.conf": "# hand-written\n"}
    for name, text in others.items():
        (st.conf_dir / name).write_text(text, encoding="utf-8")
    before = {n: os.stat(st.conf_dir / n).st_mtime_ns for n in others}
    assert _sync(app, st, FakeRunner()).status == "applied"
    assert _sync(app, st, FakeRunner(test_rc=[1, 0])).status in ("unchanged", "failed")
    for name, text in others.items():
        assert (st.conf_dir / name).read_text(encoding="utf-8") == text
        assert os.stat(st.conf_dir / name).st_mtime_ns == before[name]
    written = {p.name for p in st.conf_dir.iterdir()} - set(others)
    assert written <= {"schools.conf", ".nginx-sync.lock"}, written


def test_template_matches_the_live_block_settings(app, st, two_schools):
    from app.services.nginx_sync import render_file
    with app.app_context():
        text = render_file(st)
    for needle in ("client_max_body_size 20M;", "http2 on;", "listen [::]:443 ssl;",
                   "listen [::]:80;", "proxy_set_header X-Forwarded-Host $host;"):
        assert needle in text, needle
    assert "12m" not in text


def test_units_command_uses_the_real_install_paths(app, tmp_path):
    (tmp_path / "wsgi.py").write_text("")
    (tmp_path / ".env").write_text("")
    out = app.test_cli_runner().invoke(args=["nginx-sync-units", "--app-dir", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert f"WorkingDirectory={tmp_path.resolve().as_posix()}" in out.output
    assert f"EnvironmentFile={(tmp_path / '.env').resolve().as_posix()}" in out.output
    assert "nginx-sync --from-queue" in out.output and "/opt/manasety/lms" not in out.output
    assert "Unit=manasety-nginx-sync.service" in out.output
    dest = tmp_path / "units"
    dest.mkdir()
    out = app.test_cli_runner().invoke(args=["nginx-sync-units", "--app-dir", str(tmp_path),
                                             "--user", "deploy", "--write", str(dest)])
    assert out.exit_code == 0, out.output
    service = (dest / "manasety-nginx-sync.service").read_text(encoding="utf-8")
    assert "User=deploy" in service and (dest / "manasety-nginx-sync.timer").exists()


def test_units_command_refuses_a_wrong_app_dir(app, tmp_path):
    out = app.test_cli_runner().invoke(args=["nginx-sync-units", "--app-dir", str(tmp_path)])
    assert out.exit_code != 0 and "wsgi.py" in out.output

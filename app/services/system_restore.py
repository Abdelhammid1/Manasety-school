"""SAAS-050 — restore the whole system from the backup files, into a NEW
database (never over the live one), with checks at every step.

    flask system-restore --db-dump <file.sql.gz> --target-db <name>
                         [--files <uploads.tar.gz>] [--config <config.tar.gz>]
                         [--apply] [--apply-config]

Without --apply it only validates and prints the plan. Steps:

  1. the dump: gzip readable, pg_dump's completion marker present, every
     table the application expects is created, row counts per table read
     from the COPY blocks — any problem refuses BEFORE anything changes;
  2. CREATE DATABASE <target> (refused when it exists or is the live one);
  3. psql -v ON_ERROR_STOP=1 --single-transaction < dump  (the password
     goes in the environment, never on the command line);
  4. checks on the new database: row count per table = the dump's, the
     migration revision vs the code's single head, tenant integrity;
  5. uploads → a NEW folder next to the live one (<root>.restored-<stamp>);
  6. config: the difference is shown (.env: key NAMES only, never values);
     --apply-config backs up the current .env and writes the restored one;
  7. the switch-over is a human step (DATABASE_URL + restart), then
     `flask smoke-check` — printed at the end.

docs/DISASTER_RECOVERY.md is the runbook built on this command.
"""
from __future__ import annotations

import difflib
import gzip
import os
import re
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sqlalchemy as sa

from ..extensions import db

COMPLETE_MARKER = "-- PostgreSQL database dump complete"
_TARGET_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_CREATE_RE = re.compile(r"^CREATE TABLE (?:public\.)?\"?([a-z0-9_]+)\"? \(")
_COPY_RE = re.compile(r"^COPY (?:public\.)?\"?([a-z0-9_]+)\"? .* FROM stdin;$")


class SystemRestoreError(Exception):
    """Refused or failed; the message is safe to print (no secrets)."""


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0


@dataclass
class Report:
    dry_run: bool
    steps: list = field(default_factory=list)
    rows: dict = field(default_factory=dict)
    next_steps: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    def add(self, name, ok, detail="", started=None):
        self.steps.append(Step(name, ok, detail, round(time.monotonic() - started, 2) if started else 0.0))
        if not ok:
            raise SystemRestoreError(f"{name}: {detail}")

    def as_dict(self):
        return {"ok": self.ok, "dry_run": self.dry_run,
                "steps": [s.__dict__ for s in self.steps], "rows": self.rows, "next_steps": self.next_steps}


# ─── 1. the dump ────────────────────────────────────────────────────

@dataclass
class DumpInfo:
    tables: set
    rows: dict
    complete: bool


def inspect_dump(path) -> DumpInfo:
    """Read the whole (gzipped, plain-format) dump once: tables created,
    rows per COPY block, completion marker. Raises on an unreadable file."""
    tables, rows = set(), {}
    complete, copying, current = False, False, None
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="strict") as fh:
            for raw in fh:
                line = raw.rstrip("\r\n")              # pg_dump on Windows writes CRLF
                if copying:
                    if line == "\\.":
                        copying = False
                    else:
                        rows[current] = rows.get(current, 0) + 1
                    continue
                m = _CREATE_RE.match(line)
                if m:
                    tables.add(m.group(1))
                    complete = False
                    continue
                m = _COPY_RE.match(line)
                if m:
                    current, copying, complete = m.group(1), True, False
                    rows.setdefault(current, 0)
                    continue
                if line.startswith(COMPLETE_MARKER):
                    complete = True
                elif line.strip() and not line.startswith(("--", "\\")):
                    # Only comments, blank lines and psql meta-commands may
                    # follow the marker (pg_dump >= 17.6 ends with an
                    # unrestrict line): anything else = not the real end.
                    complete = False
    except (OSError, EOFError, UnicodeDecodeError, gzip.BadGzipFile):
        raise SystemRestoreError("ملف الـ dump تالف أو مش gzip صالح.") from None
    if copying:
        complete = False                        # cut inside a COPY block
    return DumpInfo(tables=tables, rows=rows, complete=complete)


def expected_tables() -> set:
    return {t.name for t in db.metadata.tables.values()}


# ─── 2-4. database ──────────────────────────────────────────────────

def _admin_url(target: Optional[str] = None) -> sa.engine.URL:
    url = sa.engine.make_url(str(db.engine.url))
    if url.get_backend_name() != "postgresql":
        raise SystemRestoreError("الاسترجاع الكامل محتاج PostgreSQL.")
    return url.set(database=target or "postgres")


def _psql_env(url: sa.engine.URL) -> dict:
    env = dict(os.environ)
    env.update({"PGHOST": url.host or "localhost", "PGPORT": str(url.port or 5432),
                "PGUSER": url.username or "", "PGDATABASE": url.database or ""})
    if url.password:
        env["PGPASSWORD"] = url.password            # environment, not argv
    return env


def _database_exists(name: str) -> bool:
    eng = sa.create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            return bool(c.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first())
    finally:
        eng.dispose()


def _create_database(name: str) -> None:
    eng = sa.create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            c.execute(sa.text(f'CREATE DATABASE "{name}"'))      # name validated by _TARGET_RE
    finally:
        eng.dispose()


def _load_dump(path, target: str, psql: str) -> None:
    url = _admin_url(target)
    cmd = [psql, "-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction"]
    with gzip.open(path, "rb") as src:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, env=_psql_env(url))
        assert proc.stdin is not None
        try:
            shutil.copyfileobj(src, proc.stdin, 1 << 20)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        if proc.wait() != 0:
            # psql's first error line only (no data, no credentials)
            first = next((l for l in err.splitlines() if "ERROR" in l), "psql failed")
            raise SystemRestoreError(f"psql رجّع خطأ: {first[:200]}")


def _code_heads() -> set:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from flask import current_app
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(current_app.root_path).parent / "migrations"))
    return set(ScriptDirectory.from_config(cfg).get_heads())


def _check_target(target: str, info: DumpInfo, report: Report) -> None:
    from .tenant_guard import integrity_report
    eng = sa.create_engine(_admin_url(target))
    try:
        with eng.connect() as c:
            t0 = time.monotonic()
            bad = []
            for name, n in sorted(info.rows.items()):
                got = c.execute(sa.text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
                report.rows[name] = got
                if got != n:
                    bad.append(f"{name}: {got} ≠ {n}")
            report.add("row counts match the dump", not bad, "؛ ".join(bad[:5]) or
                       f"{len(info.rows)} tables, {sum(info.rows.values())} rows", t0)
            t0 = time.monotonic()
            has = sa.inspect(c).has_table("alembic_version")
            rev = c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() if has else None
            heads = _code_heads()
            note = (f"revision {rev} = code head" if rev in heads else
                    f"revision {rev}; code head {', '.join(sorted(heads))} — run `flask db upgrade` "
                    f"against the new database before switching")
            report.add("one migration head", len(heads) == 1, note, t0)
            t0 = time.monotonic()
            violations = {k: v for k, v in integrity_report(c).items() if v}
            report.add("tenant-integrity-check", not violations,
                       ", ".join(list(violations)[:3]) or "0 violations", t0)
    finally:
        eng.dispose()


# ─── 5. uploads ─────────────────────────────────────────────────────

def _restore_files(archive, report: Report, apply: bool) -> Optional[Path]:
    from .file_storage import upload_root
    t0 = time.monotonic()
    live = Path(upload_root())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = live.parent / f"{live.name}.restored-{stamp}"
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for m in members:
                n = m.name
                if (n.startswith(("/", "\\")) or ".." in n.split("/") or "\\" in n or ":" in n
                        or not (m.isfile() or m.isdir())):
                    raise SystemRestoreError(f"مسار غير مسموح في أرشيف الملفات: {n[:80]}")
            files = [m for m in members if m.isfile()]
            if apply:
                dest.mkdir(parents=True)
                for m in files:
                    out = dest / m.name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(m) as src, open(out, "wb") as fh:
                        shutil.copyfileobj(src, fh)
    except (tarfile.TarError, OSError, EOFError) as e:
        if isinstance(e, SystemRestoreError):
            raise
        raise SystemRestoreError("أرشيف الملفات تالف.") from None
    report.add("uploads", True, f"{len(files)} files → {dest if apply else '(dry run)'}", t0)
    if apply:
        report.next_steps.append(f"swap the uploads folder: mv {live} {live}.before-{stamp} && mv {dest} {live}")
    return dest if apply else None


# ─── 6. config ──────────────────────────────────────────────────────

def _env_keys(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip().removeprefix("export ").strip()] = v
    return out


def config_diff(archive, app_dir: Path) -> list[str]:
    """Human-readable differences. .env: key names only (never values)."""
    lines = []
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            new = tar.extractfile(m).read().decode("utf-8", "replace")
            name = Path(m.name).name
            if name == ".env":
                cur_path = app_dir / ".env"
                cur = _env_keys(cur_path.read_text(encoding="utf-8")) if cur_path.is_file() else {}
                nxt = _env_keys(new)
                for k in sorted(set(nxt) - set(cur)):
                    lines.append(f".env + {k}")
                for k in sorted(set(cur) - set(nxt)):
                    lines.append(f".env - {k}")
                for k in sorted(set(cur) & set(nxt)):
                    if cur[k] != nxt[k]:
                        lines.append(f".env ~ {k} (value differs — not shown)")
            else:
                lines.append(f"{m.name}: shown for review only (lives outside the app; apply by hand)")
                lines.extend(difflib.unified_diff([], new.splitlines(), lineterm="", n=0,
                                                  fromfile="(current)", tofile=m.name))
    return lines


def apply_env(archive, app_dir: Path) -> Optional[Path]:
    with tarfile.open(archive, "r:gz") as tar:
        env = next((m for m in tar.getmembers() if m.isfile() and Path(m.name).name == ".env"), None)
        if env is None:
            return None
        data = tar.extractfile(env).read()
    target = app_dir / ".env"
    backup = None
    if target.is_file():
        backup = app_dir / f".env.before-restore-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        shutil.copy2(target, backup)
        os.chmod(backup, 0o600)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return backup


# ─── the command ────────────────────────────────────────────────────

def run(*, db_dump, target_db: str, files=None, config=None, apply: bool = False,
        apply_config: bool = False, psql: str = "psql", app_dir: Optional[Path] = None) -> Report:
    report = Report(dry_run=not apply)
    t0 = time.monotonic()
    if not _TARGET_RE.match(target_db or ""):
        report.add("target database name", False, "lowercase letters, digits and _ only")
    live = sa.engine.make_url(str(db.engine.url)).database
    if target_db == live:
        report.add("target database", False, "can't restore over the live database")
    if not Path(db_dump).is_file():
        report.add("dump file", False, "not found")
    info = inspect_dump(db_dump)
    missing = sorted(expected_tables() - info.tables)
    report.add("dump readable and complete", info.complete,
               "completion marker found" if info.complete else "no completion marker — the dump is cut", t0)
    report.add("dump has every table", not missing,
               f"{len(info.tables)} tables" if not missing else "missing: " + ", ".join(missing[:5]))
    if apply:
        t0 = time.monotonic()
        if _database_exists(target_db):
            report.add("create target database", False, f"{target_db} already exists")
        _create_database(target_db)
        report.add("create target database", True, target_db, t0)
        t0 = time.monotonic()
        _load_dump(db_dump, target_db, psql)
        report.add("load the dump (psql, one transaction)", True, "", t0)
        _check_target(target_db, info, report)
    else:
        report.add("plan", True, f"would create {target_db} and load {sum(info.rows.values())} rows "
                                 f"in {len(info.rows)} tables")
    if files:
        _restore_files(files, report, apply)
    if config:
        app_dir = Path(app_dir) if app_dir else Path.cwd()
        t0 = time.monotonic()
        diff = config_diff(config, app_dir)
        report.add("config differences", True, f"{len(diff)} line(s)", t0)
        report.next_steps.extend(diff)
        if apply_config:
            backup = apply_env(config, app_dir)
            report.add("apply .env", True, f"previous saved as {backup.name}" if backup else "no .env in archive")
    if apply:
        report.next_steps += [
            f"switch: set DATABASE_URL to the {target_db} database in .env, then `sudo systemctl restart manasety`",
            "then: `flask smoke-check` (all green) — if not, point DATABASE_URL back and restart",
        ]
    return report

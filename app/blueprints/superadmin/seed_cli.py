"""SAAS-041 — `flask seed-test-schools`: two complete test schools (test-a,
test-b) on their own hosts, for isolation tests and UAT.

    flask seed-test-schools                 # full size (default), skip if present
    flask seed-test-schools --small         # small + fast (automated tests)
    flask seed-test-schools --students 60   # students per school
    flask seed-test-schools --reset         # delete the test schools and rebuild
    flask seed-test-schools --teardown      # delete the test schools only
    flask seed-test-schools --dry-run       # print what would happen, write nothing

Writes are refused without a backup (SQLite: the DB file is copied
automatically; Postgres: --backup-file <dump from the last hour>), and in
production without --i-know. Only schools this command created are ever
touched.
"""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import click
from flask import current_app

from . import bp
from ...extensions import db
from ...services import test_seed as ts

BACKUP_MAX_AGE = 3600


def _backup(backup_file: str | None, no_backup: bool) -> str:
    """A backup made now (SQLite) or a recent dump (anything else)."""
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    env = (current_app.config.get("APP_ENV") or os.environ.get("APP_ENV") or "").lower()
    if backup_file:
        p = Path(backup_file)
        if not p.is_file() or p.stat().st_size <= 0:
            raise click.ClickException(f"backup file {backup_file} is missing or empty")
        if time.time() - p.stat().st_mtime > BACKUP_MAX_AGE:
            raise click.ClickException("backup file is older than 1 hour — make a fresh dump")
        return str(p)
    if uri.startswith("sqlite:///"):
        src = Path(uri[len("sqlite:///"):])
        if src.is_file():
            dest_dir = Path(current_app.instance_path) / "backups"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{src.stem}.before-seed-{datetime.now():%Y%m%d-%H%M%S}{src.suffix}"
            shutil.copy2(src, dest)
            return str(dest)
    if no_backup and env in ("development", "testing"):
        return "(skipped: --no-backup in development)"
    raise click.ClickException("refusing to write without a backup: pass --backup-file <pg_dump made "
                               "in the last hour>")


def _write_accounts(path: Path, built: list, host_note: str) -> None:
    lines = [f"# seed-test-schools — {datetime.now():%Y-%m-%d %H:%M} — test data only, keep out of git",
             host_note, ""]
    for b in built:
        lines.append(f"[{b.slug}] {b.url}/auth/login")
        for role, (user, pw) in b.accounts.items():
            lines.append(f"  {role:<8} {user:<12} {pw}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


@bp.cli.command("seed-test-schools")
@click.option("--full/--small", "full", default=True, show_default=True,
              help="Demo size (default) or a small, fast set.")
@click.option("--students", type=click.IntRange(1, 500), default=None, help="Students per school.")
@click.option("--reset", is_flag=True, help="Delete the test schools first, then rebuild.")
@click.option("--teardown", is_flag=True, help="Delete the test schools and stop.")
@click.option("--dry-run", is_flag=True, help="Print the plan; write nothing.")
@click.option("--i-know", "i_know", is_flag=True, help="Required when APP_ENV=production.")
@click.option("--backup-file", default=None, help="A dump made in the last hour (non-SQLite).")
@click.option("--no-backup", is_flag=True, help="Development only: skip the backup.")
@click.option("--accounts-file", default=None,
              help="Where to write the accounts (default: instance/test_accounts.txt, outside git).")
def seed_test_schools(full, students, reset, teardown, dry_run, i_know, backup_file, no_backup,
                      accounts_file):
    """SAAS-041 - build test-a / test-b with full data on their own hosts."""
    env = (current_app.config.get("APP_ENV") or os.environ.get("APP_ENV") or "").lower()
    if env == "production" and not i_know:
        raise click.ClickException("APP_ENV=production: pass --i-know to build test schools here")
    size = ts.Size.full(students) if full else ts.Size.small(students)
    try:
        present = ts.existing()
    except ts.SeedRefused as e:
        raise click.ClickException(str(e)) from None
    base = current_app.config.get("BASE_DOMAIN") or "manasety.ai"

    if dry_run:
        click.echo(f"size: {size}")
        click.echo(f"present: {sorted(present) or 'none'}")
        if teardown or reset:
            click.echo(f"would delete: {sorted(present) or 'nothing'}")
        if not teardown:
            todo = list(ts.TEST_SLUGS) if reset else [s for s in ts.TEST_SLUGS if s not in present]
            click.echo(f"would build: {todo or 'nothing (already present - use --reset)'}")
            for s in todo:
                click.echo(f"  https://{s}.{base}/auth/login")
        return

    if teardown or reset or [s for s in ts.TEST_SLUGS if s not in present]:
        click.echo(f"backup: {_backup(backup_file, no_backup)}")

    if teardown or reset:
        gone = ts.teardown([s.id for s in present.values()])
        click.echo(f"deleted test schools: {gone or 'none'}")
        present = {}
        if teardown:
            return

    started = time.monotonic()
    built = []
    for slug in ts.TEST_SLUGS:
        if slug in present:
            click.echo(f"{slug}: already present (#{present[slug].id}) - skipped; --reset to rebuild")
            continue
        b = ts.build_school(slug, size)
        built.append(b)
        click.echo(f"{slug}: built #{b.school_id} {b.counts}")
    took = time.monotonic() - started

    ids = ts.owned_ids()
    problems = ts.integrity(ids)
    click.echo("")
    click.echo("integrity: " + ("OK - 0 problems" if not problems else f"{len(problems)} problem(s)"))
    for p in problems:
        click.echo(f"  ✗ {p}")

    if built:
        mode = (current_app.config.get("TENANT_RESOLUTION_MODE") or "off").lower()
        host_note = (f"# hosts resolve when TENANT_RESOLUTION_MODE is log/enforce (now: {mode}); "
                     f"on the server run `flask nginx-sync --from-queue` (queued) for the subdomains")
        path = Path(accounts_file) if accounts_file else Path(current_app.instance_path) / "test_accounts.txt"
        _write_accounts(path, built, host_note)
        click.echo("")
        click.echo(f"built in {took:.0f}s - accounts (shown once; also in {path}):")
        for b in built:
            click.echo(f"  {b.slug}: {b.url}/auth/login")
            for role, (user, pw) in b.accounts.items():
                click.echo(f"      {role:<8} {user:<12} {pw}")
        click.echo(f"  console: https://{(current_app.config.get('PLATFORM_HOSTS') or ['console.' + base])[0]}"
                   "/superadmin/login")
        if mode == "off":
            click.echo("  note: TENANT_RESOLUTION_MODE=off - school hosts don't resolve yet")
    if problems:
        raise SystemExit(1)

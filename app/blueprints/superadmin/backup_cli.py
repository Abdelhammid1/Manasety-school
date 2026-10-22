"""SAAS-046 — school backup packages from the server CLI.

    flask school-backup --school <slug> --out <file> [--encrypt]
    flask school-backup --from-queue          (the job runner, systemd / cron)
    flask school-backup-verify <file>

The encryption passphrase is read with a hidden prompt (or from the
environment variable named by --passphrase-env) — never a command-line
value, so it doesn't land in shell history or `ps`."""
from __future__ import annotations

import json
import os
from pathlib import Path

import click

from . import bp


def _passphrase(env_name: str | None, confirm: bool) -> str:
    if env_name:
        value = os.environ.get(env_name) or ""
        if not value:
            raise click.ClickException(f"${env_name} is empty")
        return value
    return click.prompt("Passphrase", hide_input=True, confirmation_prompt=confirm)


@bp.cli.command("school-backup")
@click.option("--school", "slug", default=None, help="The school's slug.")
@click.option("--out", "out", default=None, help="Output file (default: the school's backup folder).")
@click.option("--encrypt", is_flag=True, help="Encrypt with a passphrase (>= 12 characters).")
@click.option("--passphrase-env", default=None, help="Read the passphrase from this env variable.")
@click.option("--from-queue", is_flag=True, help="Run the queued school_backup jobs.")
def school_backup_command(slug, out, encrypt, passphrase_env, from_queue):
    """Export one school's package (consistent snapshot, checksums)."""
    from ...models import School
    from ...services import school_backup as sb
    if from_queue:
        from ...services import school_backups, school_restore
        click.echo(f"processed {sb.run_backup_queue()} platform backup job(s), "
                   f"{school_backups.run_queue()} school backup request(s), "
                   f"{school_restore.run_queue()} restore step(s)")
        return
    if not slug:
        raise click.ClickException("pass --school <slug> (or --from-queue)")
    school = School.query.filter_by(slug=slug).first()
    if school is None:
        raise click.ClickException(f"no school {slug!r}")
    passphrase = _passphrase(passphrase_env, confirm=True) if encrypt else None
    if passphrase is not None:
        try:
            sb.check_passphrase(passphrase)
        except sb.BackupError as e:
            raise click.ClickException(str(e)) from None
    target = Path(out) if out else None
    plain_target = target.with_name(target.name + ".plain.tar.gz") if (target and encrypt) else target
    try:
        res = sb.export_school(school.id, plain_target,
                               progress=lambda d, t, _w: click.echo(f"\r{d}/{t}", nl=False, err=True))
        click.echo("", err=True)
        path = res.path
        if encrypt:
            enc = target or path.with_name(path.name + ".enc")
            sb.encrypt_file(path, enc, passphrase)
            path.unlink()
            path = enc
    except sb.BackupError as e:
        raise click.ClickException(str(e)) from None
    click.echo(json.dumps({"file": str(path), "bytes": path.stat().st_size, "encrypted": encrypt,
                           "tables": len(res.manifest["tables"]), "files": len(res.manifest["files"]),
                           "rows": sum(t["rows"] for t in res.manifest["tables"].values())},
                          ensure_ascii=False))


@bp.cli.command("school-backup-verify")
@click.argument("path")
@click.option("--passphrase-env", default=None, help="Read the passphrase from this env variable.")
@click.option("--school", "slug", default=None, help="Also require the package to be this school's.")
def school_backup_verify_command(path, passphrase_env, slug):
    """Verify a package; exit 1 when it can't be trusted. Writes nothing."""
    from ...models import School
    from ...services import school_backup as sb
    passphrase = None
    if Path(path).is_file() and sb.is_encrypted(path):
        passphrase = _passphrase(passphrase_env, confirm=False)
    expect = None
    if slug:
        school = School.query.filter_by(slug=slug).first()
        if school is None:
            raise click.ClickException(f"no school {slug!r}")
        expect = school.id
    rep = sb.verify_package(path, passphrase, expect_school_id=expect)
    click.echo(json.dumps(rep.as_dict(), ensure_ascii=False, indent=1))
    if not rep.ok:
        raise SystemExit(1)


@bp.cli.command("school-restore")
@click.option("--school", "slug", required=True, help="The school's slug.")
@click.option("--package", "package", required=True, help="Package file (.tar.gz or encrypted).")
@click.option("--modules", default="", help="Comma-separated modules (default: all but accounts).")
@click.option("--mode", type=click.Choice(["replace", "add_missing"]), default="replace", show_default=True)
@click.option("--passphrase-env", default=None, help="Read the passphrase from this env variable.")
@click.option("--reason", default="", help="Why (required with --apply; goes to the audit log).")
@click.option("--apply", "apply_", is_flag=True, help="Really restore (default: preview only).")
def school_restore_command(slug, package, modules, mode, passphrase_env, reason, apply_):
    """SAAS-048 — preview (default) or run a school restore from the server.
    Same engine and checks as the admin page; a restore point first."""
    import tempfile
    from ...extensions import db
    from ...models import AuditLog, School
    from ...services import school_backup as sb
    from ...services import school_restore as sr
    school = School.query.filter_by(slug=slug).first()
    if school is None:
        raise click.ClickException(f"no school {slug!r}")
    if apply_ and len(reason.strip()) < 5:
        raise click.ClickException("--apply needs --reason (written to the audit log)")
    chosen = [m for m in modules.split(",") if m] or [m.key for m in sr.MODULES if not m.explicit_only]
    tmpdir = None
    path = Path(package)
    try:
        if sb.is_encrypted(path):
            tmpdir = Path(tempfile.mkdtemp(prefix="mnst-restore-cli-", dir=sb.backups_root()))
            plain = tmpdir / "package.tar.gz"
            try:
                sb.decrypt_file(path, plain, _passphrase(passphrase_env, confirm=False))
            except sb.BackupError as e:
                raise click.ClickException(str(e)) from None
            path = plain
        try:
            pkg = sr.open_verified(path, school.id)
            try:
                mods, added = sr.with_dependencies(chosen)
                plan = sr.preview(pkg, school.id, mods, mode)
            finally:
                pkg.close()
        except sr.RestoreError as e:
            raise click.ClickException(str(e)) from None
        if not apply_:
            click.echo(json.dumps({"dry_run": True, "modules": mods, "added": added, "mode": mode,
                                   "blockers": plan["blockers"],
                                   "per_module": {m["key"]: {k: sum(t[k] for t in m["tables"])
                                                             for k in ("live", "package", "insert", "update",
                                                                       "delete")}
                                                  for m in plan["modules"]}},
                                  ensure_ascii=False, indent=1))
            return
        try:
            out = sr.run_restore(school.id, path, mods, mode)
        except sr.RestoreError as e:
            raise click.ClickException(str(e)) from None
        db.session.add(AuditLog(school_id=school.id, action="restore_cli", entity_type="School",
                                entity_id=school.id, new_value={"reason": reason, "mode": mode,
                                                                "modules": mods, "result": out}))
        db.session.commit()
        click.echo(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    finally:
        if tmpdir:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


@bp.cli.command("system-restore")
@click.option("--db-dump", required=True, help="pg_dump plain-format file, gzipped (.sql.gz).")
@click.option("--target-db", required=True, help="NEW database to restore into (never the live one).")
@click.option("--files", "files", default=None, help="uploads archive (.tar.gz).")
@click.option("--config", "config", default=None, help="config archive (.tar.gz: .env, nginx, cron).")
@click.option("--apply", "apply_", is_flag=True, help="Really restore (default: validate + plan only).")
@click.option("--apply-config", is_flag=True, help="Also write the restored .env (current one backed up).")
@click.option("--psql", default="psql", show_default=True, help="psql executable.")
def system_restore_command(db_dump, target_db, files, config, apply_, apply_config, psql):
    """SAAS-050 — restore the whole system into a new database (see
    docs/DISASTER_RECOVERY.md). Exit 1 on any failed step."""
    from ...services import system_restore as sr
    try:
        rep = sr.run(db_dump=db_dump, target_db=target_db, files=files, config=config, apply=apply_,
                     apply_config=apply_config, psql=psql)
        ok = True
    except sr.SystemRestoreError as e:
        rep, ok = None, False
        click.echo(f"REFUSED: {e}")
    if rep is not None:
        for s in rep.steps:
            click.echo(f"{'OK  ' if s.ok else 'FAIL'} {s.seconds:>7.2f}s  {s.name}  {s.detail}")
        for line in rep.next_steps:
            click.echo(f"  next: {line}")
        click.echo("system-restore: " + ("dry run — nothing changed" if rep.dry_run else "done"))
    if not ok:
        raise SystemExit(1)

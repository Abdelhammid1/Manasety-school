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
        from ...services import school_backups
        click.echo(f"processed {sb.run_backup_queue()} platform backup job(s), "
                   f"{school_backups.run_queue()} school backup request(s)")
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

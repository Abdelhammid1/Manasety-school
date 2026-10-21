"""SAAS-025 — `flask platform-user-create`: the only way to create the
first platform user. The password is prompted (hidden), never passed as
an argument, so it can't land in shell history."""
from __future__ import annotations

import click

from . import bp
from ...extensions import db
from ...models import PLATFORM_ROLES, PlatformUser
from ...services import platform_auth as pa


@bp.cli.command("platform-user-create")
@click.option("--email", required=True)
@click.option("--name", "full_name", required=True)
@click.option("--role", type=click.Choice(PLATFORM_ROLES), required=True)
def platform_user_create(email, full_name, role):
    """Create a platform (Super Admin) user. Must change the password and
    enrol TOTP at first login."""
    email = email.strip().lower()
    if "@" not in email:
        raise click.ClickException("invalid e-mail")
    if PlatformUser.query.filter_by(email=email).first() is not None:
        raise click.ClickException("a platform user with this e-mail already exists")
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    problem = pa.password_problem(password)
    if problem:
        raise click.ClickException(f"password must be at least {pa.MIN_PASSWORD_LEN} characters")
    user = PlatformUser(email=email, full_name=full_name.strip(), role=role, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    pa.audit("platform_user_created_cli", user, role=role)
    db.session.commit()
    click.echo(f"created platform user #{user.id} ({role}); password change + TOTP required at first login")


@bp.cli.command("school-provision")
@click.option("--name", required=True, help="School name (Arabic).")
@click.option("--slug", required=True)
@click.option("--plan", "plan_code", default="internal", show_default=True)
@click.option("--admin-name", required=True)
@click.option("--admin-username", default="admin", show_default=True)
@click.option("--admin-email", default="")
@click.option("--months", type=int, default=None, help="Subscription length; omit for open-ended.")
@click.option("--trial-days", type=int, default=None)
@click.option("--dry-run", is_flag=True, help="Print what would be created; write nothing.")
def school_provision(name, slug, plan_code, admin_name, admin_username, admin_email, months,
                     trial_days, dry_run):
    """SAAS-028 — CLI equivalent of the console wizard. The setup link is
    printed once; it is not stored or logged anywhere."""
    from ...models import Plan
    from ...services import provisioning as prov
    from ...services.subscriptions import get_settings, platform_today
    plan = Plan.query.filter_by(code=plan_code).first()
    if plan is None:
        raise click.ClickException(f"unknown plan {plan_code!r}")
    spec = prov.ProvisionSpec(name=name, slug=slug, plan_id=plan.id,
                              starts_on=platform_today(get_settings()), months=months,
                              trial_days=trial_days, admin_full_name=admin_name,
                              admin_username=admin_username, admin_email=admin_email)
    try:
        result = prov.provision_school(spec, None, dry_run=dry_run)
    except prov.ProvisionError as e:
        raise click.ClickException(str(e)) from None
    if dry_run:
        click.echo(f"[dry-run] would create {result.url}:")
        for line in result.plan:
            click.echo(f"  - {line}")
        return
    click.echo(f"created school #{result.school_id} {result.url} (subdomain: {result.subdomain_status})")
    click.echo(f"set-password link (shown once, valid 72h): {result.setup_link}")


@bp.cli.command("nginx-sync")
@click.option("--check", is_flag=True, help="Print the diff against the deployed schools.conf and exit.")
@click.option("--dry-run", is_flag=True, help="Render + conflict check; write nothing, no reload.")
@click.option("--only", "only", default=None, help="Regenerate one school's block only.")
@click.option("--from-queue", is_flag=True, help="Apply pending console requests (systemd timer).")
def nginx_sync_command(check, dry_run, only, from_queue):
    """SAAS-029 — generate schools.conf and apply it with backup, nginx -t,
    reload, health verification and automatic rollback. Server only."""
    from ...services import nginx_sync
    try:
        if from_queue:
            res = nginx_sync.run_queue(check=check, dry_run=dry_run, only=only)
            if res is None:
                return                         # nothing queued: stay quiet for the timer
        else:
            res = nginx_sync.run_sync(check=check, dry_run=dry_run, only=only)
    except nginx_sync.SyncError as e:
        raise click.ClickException(str(e)) from None
    if res.diff and (check or dry_run):
        click.echo(res.diff)
    for line in res.log:
        click.echo(line)
    if res.cert_days_left is not None:
        click.echo(f"certificate: {res.cert_days_left} day(s) left")
    click.echo(f"result: {res.status}")
    if res.status == "failed":
        raise SystemExit(1)


@bp.cli.command("nginx-sync-units")
@click.option("--app-dir", default=None, help="The app checkout (default: this one).")
@click.option("--env-file", default=None, help="The service env file (default: <app-dir>/.env).")
@click.option("--user", default=None, help="Run as this user (default: root, which can docker exec).")
@click.option("--write", "write_dir", default=None,
              help="Write the two files into this directory (e.g. /etc/systemd/system).")
def nginx_sync_units(app_dir, env_file, user, write_dir):
    """SAAS-040 — the systemd service + timer for nginx-sync, with the real
    paths of this install (no guessed /opt/... paths). Prints them, or
    writes them with --write; then: systemctl daemon-reload &&
    systemctl enable --now manasety-nginx-sync.timer"""
    import shutil
    import sys
    from pathlib import Path
    from flask import current_app
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    root = Path(current_app.root_path).parent
    app_dir = Path(app_dir or root).resolve()
    if not (app_dir / "wsgi.py").is_file():
        raise click.ClickException(f"{app_dir} has no wsgi.py - pass --app-dir <the lms checkout>")
    env_file = Path(env_file) if env_file else app_dir / ".env"
    if not env_file.is_file():
        raise click.ClickException(f"env file {env_file} not found - pass --env-file")
    # the flask next to the running interpreter = this venv's flask
    flask_bin = Path(sys.executable).with_name("flask")
    if not flask_bin.exists():
        found = shutil.which("flask")
        if not found:
            raise click.ClickException("can't find the flask executable of this environment")
        flask_bin = Path(found)
    env = Environment(loader=FileSystemLoader(str(root / "deploy" / "systemd")),
                      undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
    ctx = {"app_dir": app_dir.as_posix(), "env_file": env_file.resolve().as_posix(),
           "flask": flask_bin.resolve().as_posix(), "user": user}
    for name in ("manasety-nginx-sync.service", "manasety-nginx-sync.timer"):
        text = env.get_template(name + ".j2").render(**ctx)
        if write_dir:
            dest = Path(write_dir) / name
            dest.write_text(text, encoding="utf-8")
            click.echo(f"wrote {dest}")
        else:
            click.echo(f"# ===== {name} =====")
            click.echo(text)
    click.echo("next: systemctl daemon-reload && systemctl enable --now manasety-nginx-sync.timer "
               "&& systemctl list-timers manasety-nginx-sync.timer")


@bp.cli.command("support-events-prune")
@click.option("--months", type=int, default=12, show_default=True)
def support_events_prune(months):
    """SAAS-031 — drop support_session_events older than the retention
    window (default 12 months). Sessions themselves are kept."""
    from datetime import datetime, timedelta, timezone
    from ...models import SupportSessionEvent
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * months)
    from ...services.platform_security import audit_prune
    with audit_prune(db.session.connection()):          # SAAS-036 immutability
        n = SupportSessionEvent.query.filter(SupportSessionEvent.ts < cutoff).delete(synchronize_session=False)
    pa.audit("support_events_pruned", None, rows=n, months=months)
    db.session.commit()
    click.echo(f"pruned {n} support event(s) older than {months} months")

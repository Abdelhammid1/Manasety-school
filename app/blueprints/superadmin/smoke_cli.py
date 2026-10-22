"""SAAS-042 — `flask smoke-check`: run after every deploy (last step of
the deploy protocol, after `systemctl status`). Read-only."""
from __future__ import annotations

import click

from . import bp


@bp.cli.command("smoke-check")
@click.option("--base-url", default="https://lms.manasety.ai", show_default=True)
@click.option("--console-url", default="https://console.manasety.ai", show_default=True)
@click.option("--school-url", default="https://test-a.manasety.ai", show_default=True,
              help="Test school whose accounts log in (SAAS-041); '' to skip the logins.")
@click.option("--accounts-file", default=None,
              help="seed-test-schools' accounts file (default: instance/test_accounts.txt).")
@click.option("--no-cert", is_flag=True, help="Skip the certificate-expiry checks.")
@click.option("--timeout", type=float, default=15, show_default=True)
def smoke_check(base_url, console_url, school_url, accounts_file, no_cert, timeout):
    """PASS / FAIL / SKIP per check with its time; non-zero exit on any FAIL
    (SKIP — e.g. no test-school accounts here — never fails the run)."""
    from pathlib import Path
    from flask import current_app
    from ...services import smoke
    path = Path(accounts_file) if accounts_file else Path(current_app.instance_path) / "test_accounts.txt"
    accounts = smoke.read_accounts(path) if school_url and path.is_file() else {}
    rep = smoke.run(base_url=base_url, console_url=console_url, school_url=school_url or None,
                    accounts=accounts, transport=smoke.Transport(timeout), check_cert=not no_cert)
    for r in rep.results:
        label = "SKIP" if r.skipped else ("PASS" if r.ok else "FAIL")
        click.echo(f"{label}  {r.ms:>6} ms  {r.name}  {r.detail}")
    click.echo("smoke-check: " + ("all green" if rep.ok else "FAILED"))
    if not rep.ok:
        raise SystemExit(1)

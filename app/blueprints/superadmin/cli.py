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

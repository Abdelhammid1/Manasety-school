from flask import Blueprint

# cli_group=None → commands register at top level: `flask cron-tick`.
bp = Blueprint("cron", __name__, cli_group=None)

from . import routes  # noqa: E402,F401

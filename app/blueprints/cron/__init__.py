from flask import Blueprint

bp = Blueprint("cron", __name__)

from . import routes  # noqa: E402,F401

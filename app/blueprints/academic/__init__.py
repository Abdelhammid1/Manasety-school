from flask import Blueprint

bp = Blueprint("academic", __name__, template_folder="../../templates/academic")

from . import routes           # noqa: E402,F401
from . import calendar_routes  # noqa: E402,F401  Ticket #4
from . import dashboards       # noqa: E402,F401  Phase-3 A4/A5/A8

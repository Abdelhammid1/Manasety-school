from flask import Blueprint

bp = Blueprint("attendance", __name__, template_folder="../../templates/attendance")

from . import routes      # noqa: E402,F401
from . import analytics   # noqa: E402,F401  Phase-3 T1/T6/T7
from . import rules_admin # noqa: E402,F401  Deferred T3/T4 admin

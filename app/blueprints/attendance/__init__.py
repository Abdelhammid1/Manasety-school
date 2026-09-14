from flask import Blueprint

bp = Blueprint("attendance", __name__, template_folder="../../templates/attendance")

from . import routes  # noqa: E402,F401

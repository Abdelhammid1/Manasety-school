from flask import Blueprint

bp = Blueprint("schedule", __name__, template_folder="../../templates/schedule")

from . import routes  # noqa: E402,F401

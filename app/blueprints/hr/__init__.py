from flask import Blueprint

bp = Blueprint("hr", __name__, template_folder="../../templates/hr")

from . import routes  # noqa: E402,F401

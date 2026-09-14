from flask import Blueprint

bp = Blueprint("academic", __name__, template_folder="../../templates/academic")

from . import routes  # noqa: E402,F401

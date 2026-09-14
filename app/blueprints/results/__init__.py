from flask import Blueprint

bp = Blueprint("results", __name__, template_folder="../../templates/results")

from . import routes  # noqa: E402,F401

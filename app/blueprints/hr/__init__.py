from flask import Blueprint

bp = Blueprint("hr", __name__, template_folder="../../templates/hr")

from . import routes  # noqa: E402,F401
from . import leave   # noqa: E402,F401  Phase-4 T2 — leave workflow

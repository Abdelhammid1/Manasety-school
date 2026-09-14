from flask import Blueprint

bp = Blueprint("students", __name__, template_folder="../../templates/students")

from . import routes  # noqa: E402,F401

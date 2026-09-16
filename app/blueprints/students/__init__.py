from flask import Blueprint

bp = Blueprint("students", __name__, template_folder="../../templates/students")

from . import routes         # noqa: E402,F401
from . import student_tabs   # noqa: E402,F401  Sprint 17 — health/docs/behavior tabs

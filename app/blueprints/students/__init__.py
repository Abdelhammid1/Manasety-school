from flask import Blueprint

bp = Blueprint("students", __name__, template_folder="../../templates/students")

from . import routes         # noqa: E402,F401
from . import student_tabs   # noqa: E402,F401  Sprint 17 — health/docs/behavior tabs
from . import feature_extras # noqa: E402,F401  Phase-3 — S6/S8/S10/S11/S12
from . import previous_schools  # noqa: E402,F401  Phase-3 — S3
from . import student_lifecycle # noqa: E402,F401  Phase-3 — S1/S4/S5/S7

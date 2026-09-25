from flask import Blueprint

bp = Blueprint("lms", __name__, template_folder="../../templates")

from . import views           # noqa: E402,F401
from . import rubric_grading  # noqa: E402,F401  Sprint 19 — rubric scoring
from . import reports         # noqa: E402,F401  P1-18 split
from . import announcements   # noqa: E402,F401  P1-18 split
from . import passages        # noqa: E402,F401  P1-18 split
from . import taxonomy        # noqa: E402,F401  Phase-2 CRUD
from . import quiz_runtime    # noqa: E402,F401  Phase-2 runtime API

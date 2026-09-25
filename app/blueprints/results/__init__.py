from flask import Blueprint

bp = Blueprint("results", __name__, template_folder="../../templates/results")

from . import routes     # noqa: E402,F401
from . import advanced   # noqa: E402,F401  Sprint 17 — scales, rubrics, transcripts
from . import analytics  # noqa: E402,F401  Phase-4 T3 — missing grades + class avg

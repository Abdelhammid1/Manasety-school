from flask import Blueprint

bp = Blueprint("finance", __name__, template_folder="../../templates/finance")

from . import routes         # noqa: E402,F401
from . import discounts      # noqa: E402,F401  Sprint 17 — discount types
from . import refund_petty   # noqa: E402,F401  Phase-4 T5

"""Platform blueprint — hosts sprint-16/17 admin features that don't
belong to a pre-existing domain blueprint:
  · Ticket #7  — Rooms
  · Ticket #9b — Staff attendance + substitutions
  · Ticket #14 — User scopes
  · Ticket #5  — Excel imports
"""
from flask import Blueprint

bp = Blueprint("platform", __name__, template_folder="../../templates/platform")

from . import rooms         # noqa: E402,F401
from . import staff         # noqa: E402,F401
from . import scopes        # noqa: E402,F401
from . import imports       # noqa: E402,F401
from . import audit_viewer  # noqa: E402,F401  T6 — AuditLog UI

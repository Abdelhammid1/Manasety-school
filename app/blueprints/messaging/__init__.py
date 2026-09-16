"""Ticket #13 — two-way messaging blueprint."""
from flask import Blueprint

bp = Blueprint("messaging", __name__, template_folder="../../templates/messaging")

from . import routes  # noqa: E402,F401

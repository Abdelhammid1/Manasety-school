from flask import Blueprint

bp = Blueprint("courses", __name__, template_folder="../../templates")

from . import views  # noqa: E402,F401

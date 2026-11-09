from flask import Blueprint

bp = Blueprint("portal", __name__, template_folder="../../templates/portal")

from . import routes  # noqa: E402,F401
from . import parent_follow  # noqa: E402,F401

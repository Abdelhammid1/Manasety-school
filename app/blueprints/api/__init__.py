from flask import Blueprint

bp = Blueprint("api", __name__)

from . import routes  # noqa: E402,F401
from . import public  # noqa: E402,F401  SAAS-037

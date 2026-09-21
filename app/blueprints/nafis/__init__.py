from flask import Blueprint

bp = Blueprint("nafis", __name__)

from . import routes  # noqa: E402, F401

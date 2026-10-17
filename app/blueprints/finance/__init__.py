import re

from flask import Blueprint, abort, request
from flask_login import current_user

bp = Blueprint("finance", __name__, template_folder="../../templates/finance")


# ─── Parent/learner access carve-out ─────────────────────────────────
# The parent role carries `finance.view` so they can open their own
# children's invoices. The permission system doesn't distinguish
# "view-your-own-invoice" from "view-the-whole-general-ledger", so
# without this filter a parent URL-poking `/finance/dashboard`,
# `/finance/reports/balance-sheet`, `/finance/accounts`, `/finance/
# treasury`, `/finance/journal` etc. gets a full 200 with the
# school's books.
#
# Keep two paths open for non-finance.edit users:
#   * `/finance/invoices`               (list — view routes filter rows)
#   * `/finance/invoices/<id>[/print]`  (detail / printable)
# Everything else requires `finance.edit`.
_PARENT_ALLOWED = re.compile(
    r"^/finance/invoices(?:/\d+(?:/print)?)?/?$"
)


@bp.before_request
def _restrict_finance_admin_paths():
    # Unauthenticated requests fall through to the route's own
    # @login_required decorator — nothing to do here.
    if not current_user.is_authenticated:
        return None
    # Admin / finance staff: unrestricted.
    try:
        if current_user.can("finance", "edit"):
            return None
    except Exception:
        return None
    path = request.path or ""
    if _PARENT_ALLOWED.match(path):
        return None
    # Non-editor hitting an admin-only finance URL → 403. (Deliberately
    # not 404 because the invoice list the parent CAN open does link
    # elsewhere in finance, so a confusing "not found" would be worse
    # than an explicit "no access".)
    abort(403)


from . import routes         # noqa: E402,F401
from . import discounts      # noqa: E402,F401  Sprint 17 — discount types
from . import refund_petty   # noqa: E402,F401  Phase-4 T5

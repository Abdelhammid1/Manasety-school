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
# Open to non-finance.edit users, by endpoint (a URL pattern broke silently
# when ids became link codes: parents got 403 on their own invoices):
#   * the invoice list + detail + print — those views show only the user's
#     own children's invoices;
#   * the expense pages for who holds expenses.view (the warehouse role) —
#     each route still checks its own permission.
# Everything else requires `finance.edit`.
_OPEN_ENDPOINTS = frozenset({"finance.invoices_list", "finance.invoice_detail", "finance.invoice_print"})


def _finance_gate(endpoint: str) -> bool:
    if current_user.can("finance", "edit") or endpoint in _OPEN_ENDPOINTS:
        return True
    return endpoint.startswith("finance.expense") and current_user.can("expenses", "view")


@bp.before_request
def _restrict_finance_admin_paths():
    # Unauthenticated requests fall through to the route's own
    # @login_required decorator — nothing to do here.
    if not current_user.is_authenticated:
        return None
    try:
        if _finance_gate(request.endpoint or ""):
            return None
    except Exception:
        return None
    # 403, deliberately not 404: the invoice list a parent CAN open links
    # elsewhere in finance, so "not found" would be more confusing.
    abort(403)


from ..utils import BLUEPRINT_GATES  # noqa: E402
BLUEPRINT_GATES["finance"] = _finance_gate    # can_open() honours the same guard

from . import routes         # noqa: E402,F401
from . import discounts      # noqa: E402,F401  Sprint 17 — discount types
from . import refund_petty   # noqa: E402,F401  Phase-4 T5

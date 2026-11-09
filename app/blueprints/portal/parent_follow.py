"""Parent portal - read-only follow-up pages (invoices, attendance, grades).

Every route: login + portal.view + the parent role, and the child is always
looked up inside the CURRENT parent's own children (parent_user_id AND
school_id). A child_id / invoice id that is not theirs is a 404: no data.
"""
from collections import OrderedDict
from datetime import date, timedelta
from functools import wraps

from flask import abort, render_template, request
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...models.attendance import Attendance
from ...models.finance import Invoice
from ...models.lms import Submission
from ...models.results import GradeEntry
from ...models.student import Enrollment, Student
from ...models.teacher import Period, Subject

HIDDEN_INVOICE_STATUSES = ("draft", "cancelled", "void")
ATTENDANCE_RANGES = (7, 30, 90, 365)


def _sid() -> int:
    from ...services.tenancy import current_school_id
    return current_school_id()


def _parent_only(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        role = getattr(getattr(current_user, "role", None), "name", None)
        if role != "parent":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _children():
    return (Student.query
            .filter_by(school_id=_sid(), parent_user_id=current_user.id)
            .order_by(Student.full_name).all())


def _pick(children, default_first):
    """The child named by ?child_id=, from this parent's own children only."""
    raw = request.args.get("child_id")
    if raw in (None, ""):
        return children[0] if (default_first and children) else None
    try:
        cid = int(raw)
    except (TypeError, ValueError):
        abort(404)
    for c in children:
        if c.id == cid:
            return c
    abort(404)


@bp.route("/follow/invoices")
@login_required
@require_permission("portal", "view")
@_parent_only
def parent_invoices():
    children = _children()
    child = _pick(children, default_first=False)
    ids = [child.id] if child else [c.id for c in children]
    invoices = []
    if ids:
        invoices = (
            Invoice.query
            .filter(Invoice.school_id == _sid(),
                    Invoice.status.notin_(HIDDEN_INVOICE_STATUSES))
            .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
            .filter(Enrollment.student_id.in_(ids))
            .order_by(Invoice.issue_date.desc(), Invoice.id.desc())
            .limit(300).all()
        )
    totals = {
        "total": sum(float(i.total_amount or 0) for i in invoices),
        "paid": sum(float(i.paid_amount or 0) for i in invoices),
    }
    totals["remaining"] = totals["total"] - totals["paid"]
    return render_template("portal/parent_invoices.html", children=children,
                           child=child, invoices=invoices, totals=totals,
                           today=date.today())


@bp.route("/follow/invoices/<hid:invoice_id>")
@login_required
@require_permission("portal", "view")
@_parent_only
def parent_invoice_detail(invoice_id):
    ids = [c.id for c in _children()]
    inv = Invoice.query.filter_by(id=invoice_id, school_id=_sid()).first()
    if (inv is None or inv.status in HIDDEN_INVOICE_STATUSES
            or inv.enrollment is None or inv.enrollment.student_id not in ids):
        abort(404)
    payments = sorted(inv.payments, key=lambda p: (p.payment_date, p.id))
    return render_template("portal/parent_invoice_detail.html", inv=inv,
                           student=inv.enrollment.student, payments=payments,
                           today=date.today())


@bp.route("/follow/attendance")
@login_required
@require_permission("portal", "view")
@_parent_only
def parent_attendance():
    children = _children()
    child = _pick(children, default_first=True)
    days = request.args.get("days", type=int)
    if days not in ATTENDANCE_RANGES:
        days = 30
    rows, counts = [], {}
    periods, subjects = {}, {}
    if child:
        since = date.today() - timedelta(days=days)
        rows = (
            Attendance.query
            .filter(Attendance.school_id == _sid(), Attendance.date >= since)
            .join(Enrollment, Enrollment.id == Attendance.enrollment_id)
            .filter(Enrollment.student_id == child.id)
            .order_by(Attendance.date.desc(), Attendance.id.desc())
            .limit(500).all()
        )
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        periods = {p.id: p.name for p in Period.query.filter_by(school_id=_sid())}
        subjects = {s.id: s.name for s in Subject.query.filter_by(school_id=_sid())}
    return render_template("portal/parent_attendance.html", children=children,
                           child=child, rows=rows, counts=counts, days=days,
                           ranges=ATTENDANCE_RANGES, periods=periods,
                           subjects=subjects)


@bp.route("/follow/grades")
@login_required
@require_permission("portal", "view")
@_parent_only
def parent_grades():
    children = _children()
    child = _pick(children, default_first=True)
    groups, subs = [], []
    if child:
        entries = (
            GradeEntry.query
            .filter(GradeEntry.school_id == _sid())
            .join(Enrollment, Enrollment.id == GradeEntry.enrollment_id)
            .filter(Enrollment.student_id == child.id)
            .all()
        )

        def _key(e):
            c = e.component
            term = c.term if c else None
            subj = c.subject if c else None
            return ((term.order_index if term else 0),
                    (term.name if term else ""),
                    (subj.name if subj else ""))

        bucket = OrderedDict()
        for e in sorted(entries, key=_key):
            _o, tname, sname = _key(e)
            g = bucket.setdefault((tname, sname), {
                "term": tname, "subject": sname, "items": [],
                "total": 0.0, "max_total": 0.0})
            mx = float(e.component.max_score or 0) if e.component else 0.0
            sc = float(e.score or 0)
            g["items"].append({"name": e.component.name if e.component else "",
                               "score": sc, "max": mx})
            g["total"] += sc
            g["max_total"] += mx
        groups = list(bucket.values())
        subs = (
            Submission.query
            .filter(Submission.student_id == child.id,
                    Submission.score.isnot(None))
            .order_by(Submission.graded_at.desc().nullslast(),
                      Submission.submitted_at.desc())
            .limit(100).all()
        )
    return render_template("portal/parent_grades.html", children=children,
                           child=child, groups=groups, subs=subs)

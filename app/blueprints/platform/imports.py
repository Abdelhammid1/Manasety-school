"""Ticket #5 — Excel bulk import (students / teachers / guardians /
questions).

Two-step flow:
  1. GET  /platform/imports          — pick entity + download template.
  2. POST /platform/imports/preview  — server parses the uploaded file,
                                       shows a per-row status table.
  3. POST /platform/imports/commit   — writes the sane rows in one
                                       transaction, records the batch.
"""
import json
import io
from datetime import date, datetime

from flask import (
    abort, flash, redirect, render_template, request, send_file, session, url_for,
)
from flask_login import current_user, login_required

try:
    from openpyxl import Workbook, load_workbook
except ImportError:                    # pragma: no cover
    Workbook = None
    load_workbook = None

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    ImportBatch,
    Student, Guardian, StudentGuardian,
    Teacher, Grade, Section, Enrollment, AcademicYear,
)


ENTITY_LABELS = {
    "students": "الطلاب",
    "teachers": "المعلمين",
    "guardians": "أولياء الأمور",
}


# Column templates per entity.
COLUMNS = {
    "students": [
        "full_name", "national_id", "gender", "dob",
        "grade_name", "section_name",
        "parent_name", "parent_phone", "parent_email",
        "mother_name", "mother_phone",
    ],
    "teachers": [
        "full_name", "national_id", "specialization",
        "phone", "email", "hire_date",
    ],
    "guardians": [
        "full_name", "national_id", "phone", "phone_alt",
        "email", "occupation", "address",
    ],
}


def _sid():
    return current_user.school_id


@bp.route("/imports", endpoint="imports_home")
@login_required
@require_permission("students", "add")
def imports_home():
    if Workbook is None:
        flash("مكتبة openpyxl غير مثبتة على السيرفر.", "danger")
    batches = (
        ImportBatch.query.filter_by(school_id=_sid())
        .order_by(ImportBatch.created_at.desc()).limit(50).all()
    )
    return render_template(
        "platform/imports.html", entities=ENTITY_LABELS, batches=batches,
    )


@bp.route("/imports/template/<entity>", endpoint="imports_template")
@login_required
@require_permission("students", "add")
def imports_template(entity):
    if entity not in COLUMNS or Workbook is None:
        abort(404)
    wb = Workbook()
    ws = wb.active
    ws.title = entity
    cols = COLUMNS[entity]
    ws.append(cols)
    # add an example row so the user sees what belongs in each cell.
    ws.append([""] * len(cols))
    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"template_{entity}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _parse_rows(entity, wb):
    """Read rows from the workbook and produce (row_dict, error_or_None)."""
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h or "").strip() for h in rows[0]]
    expected = COLUMNS[entity]
    missing = [c for c in expected if c not in header]
    if missing:
        return [(None, f"أعمدة ناقصة: {', '.join(missing)}")]

    idx = {c: header.index(c) for c in expected}
    out = []
    for r in rows[1:]:
        if not r or all((v is None or str(v).strip() == "") for v in r):
            continue
        d = {c: (str(r[idx[c]]).strip() if r[idx[c]] is not None else "") for c in expected}
        out.append((d, None))
    return out


@bp.route("/imports/preview", methods=["POST"], endpoint="imports_preview")
@login_required
@require_permission("students", "add")
def imports_preview():
    entity = request.form.get("entity")
    file = request.files.get("file")
    if entity not in COLUMNS or not file or not file.filename:
        flash("اختر نوع الاستيراد وارفع ملف Excel.", "danger")
        return redirect(url_for("platform.imports_home"))
    if load_workbook is None:
        flash("openpyxl غير مثبتة.", "danger")
        return redirect(url_for("platform.imports_home"))
    try:
        wb = load_workbook(io.BytesIO(file.read()), data_only=True)
    except Exception as e:
        flash(f"تعذر قراءة الملف: {e}", "danger")
        return redirect(url_for("platform.imports_home"))

    parsed = _parse_rows(entity, wb)
    # Validate each row.
    active_year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    rows = []
    for i, (d, err) in enumerate(parsed, start=2):
        if d is None:
            rows.append({"n": i, "status": "error", "reason": err, "data": {}})
            continue
        problem = None
        if entity == "students":
            if not d["full_name"]:
                problem = "الاسم مطلوب."
            elif Student.query.filter_by(
                school_id=_sid(), national_id=d.get("national_id") or None
            ).first() and d.get("national_id"):
                problem = "رقم قومي مكرر."
        elif entity == "teachers":
            if not d["full_name"] or not d["specialization"]:
                problem = "الاسم والتخصص مطلوبان."
        elif entity == "guardians":
            if not d["full_name"]:
                problem = "اسم ولي الأمر مطلوب."
        rows.append({
            "n": i,
            "status": "error" if problem else "ok",
            "reason": problem, "data": d,
        })

    # Stash in session for the commit step.
    session["import_pending"] = {"entity": entity, "rows": rows}
    return render_template(
        "platform/imports_preview.html",
        entity=entity, entity_label=ENTITY_LABELS.get(entity, entity),
        rows=rows, active_year=active_year,
    )


@bp.route("/imports/commit", methods=["POST"], endpoint="imports_commit")
@login_required
@require_permission("students", "add")
def imports_commit():
    pending = session.pop("import_pending", None)
    if not pending:
        flash("لا يوجد ملف قيد المعاينة.", "danger")
        return redirect(url_for("platform.imports_home"))
    entity = pending["entity"]
    rows = pending["rows"]
    ok_rows = [r for r in rows if r["status"] == "ok"]

    batch = ImportBatch(
        school_id=_sid(), user_id=getattr(current_user, "id", None),
        entity_type=entity,
        total_rows=len(rows),
        success_rows=0, failed_rows=len([r for r in rows if r["status"] != "ok"]),
        status="pending",
        error_log=[{"n": r["n"], "reason": r["reason"]} for r in rows if r["reason"]],
    )
    db.session.add(batch); db.session.flush()

    active_year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    success = 0
    for r in ok_rows:
        d = r["data"]
        try:
            if entity == "students":
                stu = Student(
                    school_id=_sid(), full_name=d["full_name"],
                    national_id=d.get("national_id") or None,
                    gender=d.get("gender") or None,
                    dob=_parse_date(d.get("dob")),
                    parent_name=d.get("parent_name") or None,
                    parent_phone=d.get("parent_phone") or None,
                    parent_email=d.get("parent_email") or None,
                    mother_name=d.get("mother_name") or None,
                    mother_phone=d.get("mother_phone") or None,
                )
                db.session.add(stu); db.session.flush()
                # Guardians backfill (ticket 1 synergy)
                if d.get("parent_name"):
                    g = _find_or_create_guardian(
                        d["parent_name"], d.get("parent_phone"), d.get("parent_email"),
                    )
                    db.session.add(StudentGuardian(
                        student_id=stu.id, guardian_id=g.id,
                        relationship="أب", is_primary=True,
                        is_emergency_contact=True,
                    ))
                if d.get("mother_name"):
                    g = _find_or_create_guardian(
                        d["mother_name"], d.get("mother_phone"), None,
                    )
                    db.session.add(StudentGuardian(
                        student_id=stu.id, guardian_id=g.id,
                        relationship="أم",
                        is_emergency_contact=True,
                    ))
                # Optional enrollment
                if active_year and d.get("grade_name") and d.get("section_name"):
                    grade = Grade.query.filter_by(school_id=_sid(), name=d["grade_name"]).first()
                    if grade:
                        section = Section.query.filter_by(
                            school_id=_sid(), year_id=active_year.id,
                            grade_id=grade.id, name=d["section_name"],
                        ).first()
                        if section:
                            db.session.add(Enrollment(
                                school_id=_sid(),
                                student_id=stu.id, year_id=active_year.id,
                                grade_id=grade.id, section_id=section.id,
                                status="active",
                            ))
            elif entity == "teachers":
                t = Teacher(
                    school_id=_sid(), full_name=d["full_name"],
                    specialization=d.get("specialization") or "",
                    national_id=d.get("national_id") or None,
                    phone=d.get("phone") or None,
                    email=d.get("email") or None,
                    hire_date=_parse_date(d.get("hire_date")),
                )
                db.session.add(t)
            elif entity == "guardians":
                g = Guardian(
                    school_id=_sid(), full_name=d["full_name"],
                    national_id=d.get("national_id") or None,
                    phone=d.get("phone") or None,
                    phone_alt=d.get("phone_alt") or None,
                    email=d.get("email") or None,
                    occupation=d.get("occupation") or None,
                    address=d.get("address") or None,
                )
                db.session.add(g)
            success += 1
        except Exception as e:
            # Skip and log — don't blow up the batch on one bad row.
            batch.error_log = (batch.error_log or []) + [{"n": r["n"], "reason": str(e)}]
            batch.failed_rows += 1

    batch.success_rows = success
    batch.status = "completed"
    db.session.commit()
    flash(
        f"استيراد اكتمل — نجاح {success} / {batch.total_rows}. "
        f"فشل: {batch.failed_rows}.",
        "success" if success else "warning",
    )
    return redirect(url_for("platform.imports_home"))


def _find_or_create_guardian(name, phone, email):
    """Reuse a Guardian row when the same name + phone + school already
    exists (matches the backfill script logic)."""
    q = Guardian.query.filter_by(school_id=_sid(), full_name=(name or "").strip())
    if phone:
        q = q.filter_by(phone=phone)
    g = q.first()
    if g is None:
        g = Guardian(
            school_id=_sid(), full_name=(name or "").strip(),
            phone=phone or None, email=email or None,
        )
        db.session.add(g); db.session.flush()
    return g


def _parse_date(s):
    if not s: return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try: return datetime.strptime(str(s), fmt).date()
        except (ValueError, TypeError): continue
    return None

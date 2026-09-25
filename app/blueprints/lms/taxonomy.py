"""Phase-2 CRUD for Skills, LearningObjectives, QuestionCollections,
FeedbackTemplates, and AssignmentExtensions (tickets #2, #3, #24, #28, #29).

Each is a light school-scoped resource; the routes are meant to be
called from the qbank sidebar / assignment detail / submission grader.
No template surface here — endpoints redirect back to whichever page
triggered them. That keeps this file free of Jinja imports and small."""

from flask import abort, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required

from . import bp
from ...extensions import db
from ...models import (
    AssignmentExtension, CourseAssignment, FeedbackTemplate,
    LearningObjective, QuestionCollection, Skill, Student,
)
from ._helpers import _parse_dt


# ── Skills (#2) ────────────────────────────────────────────────────
@bp.route("/skills/new", methods=["POST"], endpoint="skill_new")
@login_required
def skill_new():
    title = (request.form.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    parent_id = request.form.get("parent_id", type=int) or None
    s = Skill(school_id=current_user.school_id, title=title,
              parent_id=parent_id,
              description=(request.form.get("description") or "").strip())
    db.session.add(s); db.session.commit()
    return jsonify({"id": s.id, "title": s.title, "parent_id": s.parent_id})


@bp.route("/skills/<int:sid>/delete", methods=["POST"], endpoint="skill_delete")
@login_required
def skill_delete(sid):
    s = Skill.query.filter_by(id=sid, school_id=current_user.school_id).first_or_404()
    db.session.delete(s); db.session.commit()
    return jsonify({"ok": True})


# ── Learning Objectives (#3) ───────────────────────────────────────
@bp.route("/objectives/new", methods=["POST"], endpoint="objective_new")
@login_required
def objective_new():
    title = (request.form.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    o = LearningObjective(
        school_id=current_user.school_id, title=title,
        code=(request.form.get("code") or "").strip() or None,
        lesson_id=request.form.get("lesson_id", type=int) or None,
        description=(request.form.get("description") or "").strip(),
    )
    db.session.add(o); db.session.commit()
    return jsonify({"id": o.id, "title": o.title, "code": o.code,
                    "lesson_id": o.lesson_id})


@bp.route("/objectives/<int:oid>/delete", methods=["POST"], endpoint="objective_delete")
@login_required
def objective_delete(oid):
    o = LearningObjective.query.filter_by(
        id=oid, school_id=current_user.school_id).first_or_404()
    db.session.delete(o); db.session.commit()
    return jsonify({"ok": True})


# ── Question Collections (#28) ─────────────────────────────────────
@bp.route("/collections/new", methods=["POST"], endpoint="collection_new")
@login_required
def collection_new():
    title = (request.form.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    c = QuestionCollection(
        school_id=current_user.school_id,
        owner_user_id=current_user.id, title=title,
        description=(request.form.get("description") or "").strip(),
    )
    db.session.add(c); db.session.commit()
    return jsonify({"id": c.id, "title": c.title})


@bp.route("/collections/<int:cid>/add", methods=["POST"], endpoint="collection_add")
@login_required
def collection_add(cid):
    from ...models import BankQuestion
    c = QuestionCollection.query.filter_by(
        id=cid, school_id=current_user.school_id).first_or_404()
    added = 0
    for raw in request.form.getlist("bank_ids"):
        if not raw.isdigit():
            continue
        bq = BankQuestion.query.filter_by(
            id=int(raw), school_id=current_user.school_id).first()
        if bq and bq not in c.questions:
            c.questions.append(bq)
            added += 1
    db.session.commit()
    return jsonify({"added": added})


# ── Feedback Templates (#29) ───────────────────────────────────────
@bp.route("/feedback-templates", endpoint="feedback_templates_json")
@login_required
def feedback_templates_json():
    rows = FeedbackTemplate.query.filter_by(
        school_id=current_user.school_id
    ).order_by(FeedbackTemplate.title).all()
    return jsonify([
        {"id": r.id, "title": r.title, "body": r.body} for r in rows
    ])


@bp.route("/feedback-templates/new", methods=["POST"], endpoint="feedback_template_new")
@login_required
def feedback_template_new():
    title = (request.form.get("title") or "").strip()
    body  = (request.form.get("body") or "").strip()
    if not title or not body:
        return jsonify({"error": "title + body required"}), 400
    t = FeedbackTemplate(
        school_id=current_user.school_id, owner_user_id=current_user.id,
        title=title, body=body,
    )
    db.session.add(t); db.session.commit()
    return jsonify({"id": t.id, "title": t.title, "body": t.body})


@bp.route("/feedback-templates/<int:tid>/delete", methods=["POST"],
          endpoint="feedback_template_delete")
@login_required
def feedback_template_delete(tid):
    t = FeedbackTemplate.query.filter_by(
        id=tid, school_id=current_user.school_id).first_or_404()
    db.session.delete(t); db.session.commit()
    return jsonify({"ok": True})


# ── Assignment Extensions (#24) ────────────────────────────────────
@bp.route("/assignments/<int:aid>/extensions", methods=["POST"],
          endpoint="assignment_extension_add")
@login_required
def assignment_extension_add(aid):
    role = getattr(getattr(current_user, "role", None), "name", None)
    if role not in ("admin", "teacher"):
        abort(403)
    a = CourseAssignment.query.get_or_404(aid)
    if a.course.school_id != current_user.school_id:
        abort(403)
    student_id = request.form.get("student_id", type=int)
    new_due_at = _parse_dt(request.form.get("new_due_at"))
    if not student_id or not new_due_at:
        flash("الطالب والموعد الجديد مطلوبان.", "danger")
        return redirect(url_for("lms.assignment_edit", aid=a.id))
    stu = Student.query.filter_by(
        id=student_id, school_id=current_user.school_id).first()
    if not stu:
        flash("الطالب غير موجود.", "danger")
        return redirect(url_for("lms.assignment_edit", aid=a.id))
    # UPSERT: one extension per (assignment, student).
    ext = AssignmentExtension.query.filter_by(
        assignment_id=a.id, student_id=stu.id).first()
    if ext is None:
        ext = AssignmentExtension(
            assignment_id=a.id, student_id=stu.id,
            new_due_at=new_due_at,
            granted_by_id=getattr(current_user, "id", None),
            reason=(request.form.get("reason") or "").strip(),
        )
        db.session.add(ext)
    else:
        ext.new_due_at = new_due_at
        ext.reason     = (request.form.get("reason") or "").strip()
        ext.granted_by_id = getattr(current_user, "id", None)
    db.session.commit()
    flash("تم تمديد المهلة للطالب.", "success")
    return redirect(url_for("lms.assignment_edit", aid=a.id))

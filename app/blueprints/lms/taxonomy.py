"""Phase-2 CRUD for Skills, LearningObjectives, QuestionCollections,
FeedbackTemplates, and AssignmentExtensions (tickets #2, #3, #24, #28, #29).

Each is a light school-scoped resource; the JSON routes are meant to
be called from the qbank sidebar / assignment detail / submission
grader. Ticket D4 (2026-09-26) adds a full admin page at /taxonomy
so admins can seed Skill trees and LearningObjective rows the bank
forms depend on."""

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AssignmentExtension, Course, CourseAssignment, FeedbackTemplate,
    LearningObjective, Lesson, QuestionCollection, Skill, Student,
    Subject, Unit,
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


# ── Ticket D4 (2026-09-26) — Skills + Objectives admin page ────────
#
# The dashboard-triggered JSON routes above stay for XHR callers.
# These new form-based routes drive the /taxonomy admin page: same
# CRUD but redirect back so the page can be edited without JS.

def _sid():
    return current_user.school_id


def _skills_scoped():
    return (Skill.query.filter_by(school_id=_sid())
            .order_by(Skill.parent_id.nulls_first(), Skill.order_index,
                      Skill.title).all())


def _objectives_scoped():
    return (LearningObjective.query.filter_by(school_id=_sid())
            .order_by(LearningObjective.code.nulls_last(),
                      LearningObjective.title).all())


def _lessons_scoped():
    return (Lesson.query
            .join(Course, Course.id == Lesson.course_id)
            .filter(Course.school_id == _sid())
            .order_by(Course.id, Lesson.order_index, Lesson.title).all())


@bp.route("/taxonomy", endpoint="taxonomy_home")
@login_required
@require_permission("lms", "view")
def taxonomy_home():
    return render_template(
        "lms/taxonomy_home.html",
        skills=_skills_scoped(),
        objectives=_objectives_scoped(),
        lessons=_lessons_scoped(),
    )


# ── Skills — form flavour ─────────────────────────────────────────
@bp.route("/taxonomy/skills/new", methods=["POST"],
          endpoint="taxonomy_skill_new")
@login_required
@require_permission("lms", "edit")
def taxonomy_skill_new():
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("عنوان المهارة مطلوب.", "danger")
        return redirect(url_for("lms.taxonomy_home"))
    parent_id = request.form.get("parent_id", type=int) or None
    if parent_id:
        # Refuse a parent that lives in another school.
        parent = Skill.query.filter_by(id=parent_id, school_id=_sid()).first()
        if not parent:
            flash("المهارة الأم غير موجودة.", "danger")
            return redirect(url_for("lms.taxonomy_home"))
    db.session.add(Skill(
        school_id=_sid(), title=title, parent_id=parent_id,
        description=(request.form.get("description") or "").strip(),
    ))
    db.session.commit()
    flash("تمت إضافة المهارة.", "success")
    return redirect(url_for("lms.taxonomy_home"))


@bp.route("/taxonomy/skills/<int:sid>/edit", methods=["POST"],
          endpoint="taxonomy_skill_edit")
@login_required
@require_permission("lms", "edit")
def taxonomy_skill_edit(sid):
    s = Skill.query.filter_by(id=sid, school_id=_sid()).first_or_404()
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("عنوان المهارة مطلوب.", "danger")
        return redirect(url_for("lms.taxonomy_home"))
    new_parent = request.form.get("parent_id", type=int) or None
    if new_parent == s.id:
        flash("لا يمكن جعل المهارة أمًا لنفسها.", "danger")
        return redirect(url_for("lms.taxonomy_home"))
    s.title = title
    s.description = (request.form.get("description") or "").strip()
    s.parent_id = new_parent
    db.session.commit()
    flash("تم تحديث المهارة.", "success")
    return redirect(url_for("lms.taxonomy_home"))


@bp.route("/taxonomy/skills/<int:sid>/delete", methods=["POST"],
          endpoint="taxonomy_skill_delete")
@login_required
@require_permission("lms", "delete")
def taxonomy_skill_delete(sid):
    s = Skill.query.filter_by(id=sid, school_id=_sid()).first_or_404()
    # Children stay alive with parent_id nulled (matches the FK's
    # ON DELETE SET NULL). Bank question tags cascade via M:N.
    db.session.delete(s); db.session.commit()
    flash("تم حذف المهارة.", "success")
    return redirect(url_for("lms.taxonomy_home"))


# ── Learning Objectives — form flavour ────────────────────────────
@bp.route("/taxonomy/objectives/new", methods=["POST"],
          endpoint="taxonomy_objective_new")
@login_required
@require_permission("lms", "edit")
def taxonomy_objective_new():
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("عنوان ناتج التعلم مطلوب.", "danger")
        return redirect(url_for("lms.taxonomy_home"))
    lesson_id = request.form.get("lesson_id", type=int) or None
    if lesson_id:
        lesson = (Lesson.query.join(Course)
                  .filter(Lesson.id == lesson_id,
                          Course.school_id == _sid()).first())
        if not lesson:
            flash("الدرس المحدد غير موجود في هذه المدرسة.", "danger")
            return redirect(url_for("lms.taxonomy_home"))
    db.session.add(LearningObjective(
        school_id=_sid(), title=title,
        code=(request.form.get("code") or "").strip() or None,
        lesson_id=lesson_id,
        description=(request.form.get("description") or "").strip(),
    ))
    db.session.commit()
    flash("تمت إضافة ناتج التعلم.", "success")
    return redirect(url_for("lms.taxonomy_home"))


@bp.route("/taxonomy/objectives/<int:oid>/edit", methods=["POST"],
          endpoint="taxonomy_objective_edit")
@login_required
@require_permission("lms", "edit")
def taxonomy_objective_edit(oid):
    o = LearningObjective.query.filter_by(
        id=oid, school_id=_sid()).first_or_404()
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("عنوان ناتج التعلم مطلوب.", "danger")
        return redirect(url_for("lms.taxonomy_home"))
    lesson_id = request.form.get("lesson_id", type=int) or None
    if lesson_id:
        lesson = (Lesson.query.join(Course)
                  .filter(Lesson.id == lesson_id,
                          Course.school_id == _sid()).first())
        if not lesson:
            flash("الدرس المحدد غير موجود في هذه المدرسة.", "danger")
            return redirect(url_for("lms.taxonomy_home"))
    o.title = title
    o.code = (request.form.get("code") or "").strip() or None
    o.lesson_id = lesson_id
    o.description = (request.form.get("description") or "").strip()
    db.session.commit()
    flash("تم تحديث ناتج التعلم.", "success")
    return redirect(url_for("lms.taxonomy_home"))


@bp.route("/taxonomy/objectives/<int:oid>/delete", methods=["POST"],
          endpoint="taxonomy_objective_delete")
@login_required
@require_permission("lms", "delete")
def taxonomy_objective_delete(oid):
    o = LearningObjective.query.filter_by(
        id=oid, school_id=_sid()).first_or_404()
    db.session.delete(o); db.session.commit()
    flash("تم حذف ناتج التعلم.", "success")
    return redirect(url_for("lms.taxonomy_home"))

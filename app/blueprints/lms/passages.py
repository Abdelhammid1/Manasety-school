"""Reading-passage library (ticket P1-18 split)."""

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user

from . import bp
from ...extensions import db
from ...models import BankQuestion, Grade, Passage, Subject


@bp.route("/passages", endpoint="passages_home")
@login_required
def passages_home():
    """Reading-passage library — Stitch lms_7 shell/list."""
    sid = current_user.school_id
    items = (
        Passage.query.filter_by(school_id=sid)
        .order_by(Passage.updated_at.desc()).limit(200).all()
    )
    subjects = Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
    return render_template("lms/passages_home.html",
                           items=items, subjects=subjects)


@bp.route("/passages/new", methods=["GET", "POST"], endpoint="passage_new")
@login_required
def passage_new():
    return _passage_form(None)


@bp.route("/passages/<int:pid>", methods=["GET", "POST"], endpoint="passage_edit")
@login_required
def passage_edit(pid):
    p = Passage.query.filter_by(
        id=pid, school_id=current_user.school_id).first_or_404()
    return _passage_form(p)


def _passage_form(p):
    sid = current_user.school_id
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        body  = (request.form.get("body") or "").strip()
        if not title:
            flash("عنوان القطعة مطلوب.", "danger")
            return redirect(request.url)
        if p is None:
            p = Passage(school_id=sid, created_by_id=getattr(current_user, "id", None))
            db.session.add(p)
        p.title = title
        p.body = body
        p.source = (request.form.get("source") or "").strip()
        p.language = (request.form.get("language") or "ar").strip()
        p.subject_id = request.form.get("subject_id", type=int) or None
        p.grade_id   = request.form.get("grade_id",   type=int) or None
        p.state      = (request.form.get("state") or "published").strip()
        p.word_count = len([w for w in (body or "").split() if w])
        db.session.commit()
        flash("تم حفظ القطعة.", "success")
        return redirect(url_for("lms.passage_edit", pid=p.id))

    subjects = Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
    grades   = Grade.query.filter_by(school_id=sid).order_by(Grade.order_index).all()
    linked = []
    if p:
        linked = BankQuestion.query.filter_by(passage_id=p.id).all()
    return render_template("lms/passage_edit.html",
                           passage=p, subjects=subjects,
                           grades=grades, linked=linked)


@bp.route("/passages/<int:pid>/delete", methods=["POST"], endpoint="passage_delete")
@login_required
def passage_delete(pid):
    p = Passage.query.filter_by(
        id=pid, school_id=current_user.school_id).first_or_404()
    db.session.delete(p); db.session.commit()
    flash("تم حذف القطعة.", "success")
    return redirect(url_for("lms.passages_home"))

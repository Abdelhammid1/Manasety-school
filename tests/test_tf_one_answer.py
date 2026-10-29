"""Ticket «صح/خطأ بإجابتين» — a صح/خطأ question keeps exactly one correct
answer: radio buttons on the page, refused on the server (update and bank
save) with the input kept, skipped when copied from the bank; an old
broken question still opens; the read-only report lists them."""

from __future__ import annotations

import pytest

from isolation_harness import hid, host


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _client(sapp, login_as, A, role="teacher"):
    c = sapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    return c


def _add_tf(c, A, where):
    """Add a صح/خطأ question through the page; returns (question id, [choice ids])."""
    from app.extensions import db
    from app.models import AssignmentQuestion, Question
    if where == "quiz":
        url, model, parent = f"/lms/quizzes/{hid(A['quiz'])}/questions/add", Question, ("quiz_id", A["quiz"])
    else:
        url, model, parent = (f"/lms/assignments/{hid(A['assignment'])}/questions/add", AssignmentQuestion,
                              ("assignment_id", A["assignment"]))
    assert c.post(url, base_url=host(A), data={"kind": "tf", "prompt": "العدد 7 أكبر من العدد 9",
                                               "points": "5"}).status_code == 302
    with c.application.app_context():
        q = model.query.filter_by(prompt="العدد 7 أكبر من العدد 9", **{parent[0]: parent[1]}).one()
        out = (q.id, [ch.id for ch in sorted(q.choices, key=lambda x: x.order_index)])
        db.session.remove()
    return out


def _correct(sapp, where, qid):
    from app.extensions import db
    from app.models import AssignmentQuestion, Question
    with sapp.app_context():
        q = db.session.get(Question if where == "quiz" else AssignmentQuestion, qid)
        out = sorted(ch.label for ch in q.choices if ch.is_correct), q.prompt
        db.session.remove()
    return out


def _update_url(where, qid):
    return f"/lms/questions/{hid(qid)}/update" if where == "quiz" else f"/lms/assignment-questions/{hid(qid)}/update"


@pytest.mark.parametrize("where", ["quiz", "assignment"])
def test_the_page_offers_radio_buttons_for_tf(sapp, world, login_as, where):
    A = world["A"]
    c = _client(sapp, login_as, A)
    qid, (yes, no) = _add_tf(c, A, where)
    page_url = (f"/lms/quizzes/{hid(A['quiz'])}/questions" if where == "quiz"
                else f"/lms/assignments/{hid(A['assignment'])}/questions")
    body = c.get(page_url, base_url=host(A)).get_data(as_text=True)
    i = body.index(f'name="correct_choices" value="{yes}"')
    assert body[i - 30:i].rstrip().endswith('type="radio"')


@pytest.mark.parametrize("where", ["quiz", "assignment"])
@pytest.mark.parametrize("picked", ["both", "none", "foreign"])
def test_two_none_or_a_foreign_answer_is_refused_and_the_input_kept(sapp, world, login_as, where, picked):
    A = world["A"]
    c = _client(sapp, login_as, A)
    qid, (yes, no) = _add_tf(c, A, where)
    before = _correct(sapp, where, qid)
    ids = {"both": [yes, no], "none": [], "foreign": [yes, 999999]}[picked]
    r = c.post(_update_url(where, qid), base_url=host(A),
               data={"prompt": "نص معدّل", "points": "5", "correct_choices": [str(x) for x in ids]})
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and "إجابة صحيحة واحدة بالضبط" in body
    assert "نص معدّل" in body                                       # the teacher's text is still there
    assert _correct(sapp, where, qid) == before                     # nothing saved


@pytest.mark.parametrize("where", ["quiz", "assignment"])
def test_one_answer_saves(sapp, world, login_as, where):
    A = world["A"]
    c = _client(sapp, login_as, A)
    qid, (yes, no) = _add_tf(c, A, where)
    r = c.post(_update_url(where, qid), base_url=host(A),
               data={"prompt": "العدد 7 أكبر من العدد 9", "points": "5", "correct_choices": [str(no)]})
    assert r.status_code == 302
    assert _correct(sapp, where, qid) == (["خطأ"], "العدد 7 أكبر من العدد 9")


def test_an_old_tf_with_two_answers_opens_and_must_be_fixed_to_save(sapp, world, login_as):
    from app.extensions import db
    from app.models import Question
    A = world["A"]
    c = _client(sapp, login_as, A)
    qid, (yes, no) = _add_tf(c, A, "quiz")
    with sapp.app_context():
        for ch in db.session.get(Question, qid).choices:
            ch.is_correct = True
        db.session.commit(); db.session.remove()
    assert c.get(f"/lms/quizzes/{hid(A['quiz'])}/questions", base_url=host(A)).status_code == 200
    r = c.post(_update_url("quiz", qid), base_url=host(A),
               data={"prompt": "x", "points": "5", "correct_choices": [str(yes), str(no)]})
    assert r.status_code == 400


def _bank_tf(sapp, A, correct_flags):
    from app.extensions import db
    from app.models import BankChoice, BankQuestion
    with sapp.app_context():
        bq = BankQuestion(school_id=A["school"].id, prompt="bank-tf", kind="tf", review_state="approved")
        db.session.add(bq); db.session.flush()
        for i, (label, ok) in enumerate(zip(("صح", "خطأ"), correct_flags), start=1):
            db.session.add(BankChoice(question_id=bq.id, order_index=i, label=label, is_correct=ok))
        db.session.commit()
        bid = bq.id
        db.session.remove()
    return bid


@pytest.mark.parametrize("where", ["quiz", "assignment"])
def test_picking_from_the_bank_skips_a_broken_tf_and_keeps_a_good_one(sapp, world, login_as, where):
    from app.extensions import db
    from app.models import AssignmentQuestion, Question
    A = world["A"]
    good, bad = _bank_tf(sapp, A, (False, True)), _bank_tf(sapp, A, (True, True))
    c = _client(sapp, login_as, A)
    url = (f"/lms/quizzes/{hid(A['quiz'])}/pick" if where == "quiz"
           else f"/lms/assignments/{hid(A['assignment'])}/pick")
    r = c.post(url, base_url=host(A), data={"bank_ids": [str(good), str(bad)]}, follow_redirects=True)
    assert "لم يُضف 1 سؤال صح/خطأ" in r.get_data(as_text=True)
    model, col, pid = ((Question, "quiz_id", A["quiz"]) if where == "quiz"
                       else (AssignmentQuestion, "assignment_id", A["assignment"]))
    with sapp.app_context():
        copied = model.query.filter_by(**{col: pid}).filter(model.source_bank_id.in_([good, bad])).all()
        assert [q.source_bank_id for q in copied] == [good]
        assert sorted(ch.label for ch in copied[0].choices if ch.is_correct) == ["خطأ"]
        db.session.remove()


def test_the_bank_refuses_a_tf_with_two_answers(sapp, world, login_as):
    from app.models import BankQuestion
    A = world["A"]
    c = _client(sapp, login_as, A)
    r = c.post("/lms/bank/new", base_url=host(A), follow_redirects=True, data={
        "kind": "tf", "prompt": "bank two", "points": "1",
        "choice_label": ["صح", "خطأ"], "choice_correct": ["0", "1"]})
    assert "إجابة صحيحة واحدة بالضبط" in r.get_data(as_text=True)
    with sapp.app_context():
        assert BankQuestion.query.filter_by(prompt="bank two").count() == 0


def test_a_student_cannot_update_a_question(sapp, world, login_as):
    A = world["A"]
    r = _client(sapp, login_as, A, "student").post(
        _update_url("quiz", A["question"]), base_url=host(A), data={"prompt": "x", "correct_choices": []})
    assert r.status_code == 403


def test_the_report_lists_broken_tf_and_changes_nothing(sapp, world):
    from app.extensions import db
    from app.models import BankChoice
    A = world["A"]
    bad = _bank_tf(sapp, A, (True, True))
    _bank_tf(sapp, A, (True, False))
    with sapp.app_context():
        before = sorted((c.id, c.is_correct) for c in BankChoice.query.all())
        db.session.remove()
    out = sapp.test_cli_runner().invoke(args=["lms", "tf-report"]).output
    rows = [line for line in out.splitlines() if line.startswith(str(A["school"].id) + "\t")]
    assert any(f"\tbank\t{bad}\t2\t" in line for line in rows)
    assert len([r for r in rows if "\tbank\t" in r]) == 1
    assert "nothing was changed" in out
    with sapp.app_context():
        assert sorted((c.id, c.is_correct) for c in BankChoice.query.all()) == before
        db.session.remove()

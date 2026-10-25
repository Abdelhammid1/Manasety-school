"""One question-bank form for add and edit (lms/bank_smart.html): every
field of both old forms, an edit keeps what the user didn't touch, and
both old addresses open it."""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from isolation_harness import host


@pytest.fixture
def bapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


class _Form(HTMLParser):
    """What a browser would submit from #smart-q-form, untouched."""

    def __init__(self):
        super().__init__()
        self.inside = False
        self.data: list[tuple[str, str]] = []
        self._select = None
        self._textarea = None
        self._text = ""
        self.action = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and a.get("id") == "smart-q-form":
            self.inside, self.action = True, a.get("action")
        if not self.inside or "disabled" in a:
            return
        name = a.get("name")
        if tag == "input" and name:
            kind = a.get("type", "text")
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self.data.append((name, a.get("value") or "on"))
            else:
                self.data.append((name, a.get("value") or ""))
        elif tag == "select" and name:
            self._select = name
        elif tag == "option" and self._select and "selected" in a:
            self.data.append((self._select, a.get("value") or ""))
        elif tag == "textarea" and name:
            self._textarea, self._text = name, ""

    def handle_data(self, data):
        if self._textarea:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None
        elif tag == "textarea" and self._textarea:
            self.data.append((self._textarea, self._text))
            self._textarea = None
        elif tag == "form":
            self.inside = False


def _client(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


@pytest.fixture
def taxonomy(bapp, two_schools):
    from app.extensions import db
    from app.models import LearningObjective, Skill
    A = two_schools["A"]
    with bapp.app_context():
        rows = [Skill(school_id=A["school"].id, title=f"Skill-{i}") for i in range(3)] + \
               [LearningObjective(school_id=A["school"].id, title=f"Obj-{i}") for i in range(3)]
        db.session.add_all(rows); db.session.commit()
        ids = {"skills": [r.id for r in rows[:3]], "objectives": [r.id for r in rows[3:]]}
        db.session.remove()
    return ids


def _question(app, school_id, prompt):
    from app.extensions import db
    from app.models import BankQuestion
    with app.app_context():
        q = BankQuestion.query.filter_by(school_id=school_id, prompt=prompt).one()
        out = {"id": q.id, "kind": q.kind, "cognitive_level": q.cognitive_level,
               "skills": sorted(s.id for s in q.skills), "objectives": sorted(o.id for o in q.objectives),
               "subject_id": q.subject_id, "code": q.code,
               "choices": [(c.label, c.is_correct) for c in sorted(q.choices, key=lambda c: c.order_index)]}
        db.session.remove()
    return out


@pytest.mark.parametrize("path", ["/lms/bank/new", "/lms/bank/smart/new"])
def test_both_addresses_open_the_one_form_with_every_field(bapp, two_schools, login_as, path):
    A = two_schools["A"]
    r = _client(bapp, login_as, A).get(path + "?passage_id=7", base_url=host(A))
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert 'id="smart-q-form"' in page
    for name in ('name="cognitive_level"', 'name="skill_ids"', 'name="objective_ids"', 'value="multi"',
                 'name="code"', 'name="axis_id"', 'name="indicator_id"', 'name="unit_id"', 'name="lesson_id"',
                 'name="visibility"', 'name="internal_label"', 'name="hint_text"', 'name="notes"',
                 'name="explanation_video_url"', 'name="tags"', 'name="difficulty"'):
        assert name in page, name
    assert 'name="passage_id"\n           value="7"' in page or 'value="7"' in page
    # every field has its one-line explanation
    assert page.count('font-label-sm text-label-sm text-on-surface-variant') >= 20


def test_a_multi_question_saves_with_both_answers_and_its_classification(bapp, two_schools, login_as, taxonomy):
    A = two_schools["A"]
    data = [("kind", "multi"), ("prompt", "سؤال متعدد الإجابات"), ("subject_id", str(A["subject"].id)),
            ("grade_id", str(A["grade"].id)), ("cognitive_level", "analyze"), ("points", "2"),
            ("difficulty", "hard"), ("visibility", "private"),
            ("choice_label", "أ"), ("choice_label", "ب"), ("choice_label", "ج"),
            ("choice_correct", "0"), ("choice_correct", "2")]
    data += [("skill_ids", str(i)) for i in taxonomy["skills"][:2]]
    data += [("objective_ids", str(i)) for i in taxonomy["objectives"][:2]]
    from werkzeug.datastructures import MultiDict
    r = _client(bapp, login_as, A).post("/lms/bank/new", base_url=host(A), data=MultiDict(data))
    assert r.status_code == 302
    q = _question(bapp, A["school"].id, "سؤال متعدد الإجابات")
    assert q["kind"] == "multi" and q["cognitive_level"] == "analyze"
    assert q["choices"] == [("أ", True), ("ب", False), ("ج", True)]
    assert q["skills"] == sorted(taxonomy["skills"][:2]) and q["objectives"] == sorted(taxonomy["objectives"][:2])


def test_an_edit_of_the_text_only_keeps_everything_else(bapp, two_schools, login_as, taxonomy):
    """Open the edit form, change the prompt, submit what the browser
    would: Bloom, skills, objectives, scope and choices survive."""
    from werkzeug.datastructures import MultiDict
    A = two_schools["A"]
    c = _client(bapp, login_as, A)
    seed = [("kind", "mcq"), ("prompt", "قبل التعديل"), ("subject_id", str(A["subject"].id)),
            ("grade_id", str(A["grade"].id)), ("cognitive_level", "apply"),
            ("choice_label", "صح"), ("choice_label", "غلط"), ("choice_correct", "1")]
    seed += [("skill_ids", str(i)) for i in taxonomy["skills"][:2]]
    seed += [("objective_ids", str(i)) for i in taxonomy["objectives"][:2]]
    assert c.post("/lms/bank/new", base_url=host(A), data=MultiDict(seed)).status_code == 302
    before = _question(bapp, A["school"].id, "قبل التعديل")

    from flask import url_for
    with bapp.test_request_context():
        edit = url_for("lms.bank_edit", bid=before["id"])
    page = c.get(edit, base_url=host(A)).get_data(as_text=True)
    form = _Form()
    form.feed(page)
    assert form.action == edit
    assert ("code", before["code"]) in form.data and 'readonly' in page
    data = [(k, "بعد التعديل" if k == "prompt" else v) for k, v in form.data]
    assert c.post(edit, base_url=host(A), data=MultiDict(data)).status_code == 302
    after = _question(bapp, A["school"].id, "بعد التعديل")
    for key in ("id", "kind", "cognitive_level", "skills", "objectives", "subject_id", "code", "choices"):
        assert after[key] == before[key], key


def test_an_empty_prompt_saves_nothing(bapp, two_schools, login_as):
    from app.extensions import db
    from app.models import BankQuestion
    A = two_schools["A"]
    with bapp.app_context():
        n = BankQuestion.query.filter_by(school_id=A["school"].id).count()
        db.session.remove()
    r = _client(bapp, login_as, A).post("/lms/bank/new", base_url=host(A),
                                        data={"kind": "short", "prompt": "  "}, follow_redirects=True)
    assert "نص السؤال مطلوب" in r.get_data(as_text=True)
    with bapp.app_context():
        assert BankQuestion.query.filter_by(school_id=A["school"].id).count() == n
        db.session.remove()


def test_without_lms_edit_add_and_edit_are_refused(bapp, two_schools, login_as):
    from flask import url_for
    from app.extensions import db
    from app.models import BankQuestion, Role
    A = two_schools["A"]
    with bapp.app_context():
        q = BankQuestion(school_id=A["school"].id, prompt="للقراءة", kind="essay")
        db.session.add(q)
        role = db.session.get(Role, A["roles"]["teacher"].id)
        assert role is not None
        perms = dict(role.permissions or {})
        perms["lms"] = ["view"]
        role.permissions = perms
        db.session.commit()
        qid = q.id
        db.session.remove()
    with bapp.test_request_context():
        edit = url_for("lms.bank_edit", bid=qid)
    c = _client(bapp, login_as, A, "teacher")
    for path in ("/lms/bank/new", "/lms/bank/smart/new", edit):
        assert c.get(path, base_url=host(A)).status_code == 403, path
    assert c.post(edit, base_url=host(A), data={"prompt": "HACK", "kind": "essay"}).status_code == 403


def test_true_false_ignores_the_hidden_rows(bapp, two_schools, login_as):
    """The form disables rows 3..6 for tf on submit; the server never
    receives their text, so a tf question has its two choices only."""
    from werkzeug.datastructures import MultiDict
    A = two_schools["A"]
    data = MultiDict([("kind", "tf"), ("prompt", "صح ولا غلط؟"), ("subject_id", str(A["subject"].id)),
                      ("grade_id", str(A["grade"].id)),
                      ("choice_label", "صح"), ("choice_label", "خطأ"), ("choice_correct", "0")])
    assert _client(bapp, login_as, A).post("/lms/bank/new", base_url=host(A), data=data).status_code == 302
    assert _question(bapp, A["school"].id, "صح ولا غلط؟")["choices"] == [("صح", True), ("خطأ", False)]


def test_edit_keeps_the_right_answer_after_a_blank_row(bapp, two_schools, login_as):
    """Saved with a blank middle row (order_index 1 and 3), the edit form
    must tick the right choice — re-saving it keeps the correct answer."""
    from flask import url_for
    from werkzeug.datastructures import MultiDict
    A = two_schools["A"]
    c = _client(bapp, login_as, A)
    seed = MultiDict([("kind", "mcq"), ("prompt", "فراغ في النص"), ("subject_id", str(A["subject"].id)),
                      ("grade_id", str(A["grade"].id)), ("choice_label", "أ"), ("choice_label", ""),
                      ("choice_label", "ج"), ("choice_correct", "2")])
    assert c.post("/lms/bank/new", base_url=host(A), data=seed).status_code == 302
    q = _question(bapp, A["school"].id, "فراغ في النص")
    assert q["choices"] == [("أ", False), ("ج", True)]
    with bapp.test_request_context():
        edit = url_for("lms.bank_edit", bid=q["id"])
    form = _Form()
    form.feed(c.get(edit, base_url=host(A)).get_data(as_text=True))
    assert c.post(edit, base_url=host(A), data=MultiDict(form.data)).status_code == 302
    assert _question(bapp, A["school"].id, "فراغ في النص")["choices"] == [("أ", False), ("ج", True)]

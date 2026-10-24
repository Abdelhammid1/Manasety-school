"""Ready-made grading templates: the library keeps its rules, and each
type applies as the school's own copy — never touching what exists,
never crossing schools, refused without results/edit."""

from __future__ import annotations

from decimal import Decimal

import pytest
from flask import url_for

from isolation_harness import host


@pytest.fixture
def gapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _client(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


def _url(app, endpoint, **kw):
    with app.test_request_context():
        return url_for(endpoint, **kw)


def _count(app, model, **filters):
    from app.extensions import db
    with app.app_context():
        n = model.query.filter_by(**filters).count()
        db.session.remove()
    return n


# ─── the library ────────────────────────────────────────────────────

def test_the_library_keeps_its_rules_without_a_database():
    from app.services.school_templates import grading_library as lib
    assert lib.validate() == []
    assert len(lib.SCALES) == len(lib.COMPONENT_SETS) == len(lib.PASS_RULES) == len(lib.RUBRICS) == 3


def test_the_rules_catch_a_broken_template(monkeypatch):
    from app.services.school_templates import grading_library as lib
    bad_scale = lib.ScaleTemplate("x", "x", "x", "numeric", (lib.Level("a", Decimal(0), Decimal(40)),
                                                            lib.Level("b", Decimal(45), Decimal(100))))
    bad_set = lib.ComponentSet("y", "y", "y", (("a", Decimal(30)), ("b", Decimal(60))))
    bad_rule = lib.PassRuleTemplate("z", "z", "z", "overall_only", Decimal(0), Decimal(50))
    monkeypatch.setattr(lib, "SCALES", lib.SCALES + (bad_scale,))
    monkeypatch.setattr(lib, "COMPONENT_SETS", lib.COMPONENT_SETS + (bad_set, bad_set))
    monkeypatch.setattr(lib, "PASS_RULES", lib.PASS_RULES + (bad_rule,))
    problems = " | ".join(lib.validate())
    for needle in ("x: gap or overlap", "y: max scores sum to 90", "duplicate key y", "z: threshold 0"):
        assert needle in problems, needle


def test_the_default_template_still_matches_provisioning():
    from app.services.school_templates import default, grading_library as lib
    t = lib.get("scale", "percent-default")
    assert [(l.label, float(l.min_score), float(l.max_score), l.is_passing) for l in t.levels] == \
           [(a, float(b), float(c), d) for a, b, c, d in default.GRADING_SCALE[1]]


# ─── scales ─────────────────────────────────────────────────────────

def test_a_school_without_a_scale_gets_one_and_grades_with_it(gapp, two_schools, login_as):
    from app.extensions import db
    from app.models import GradingScale
    A, B = two_schools["A"], two_schools["B"]
    with gapp.app_context():
        GradingScale.query.filter_by(school_id=A["school"].id).delete()
        db.session.commit(); db.session.remove()
    b_before = _count(gapp, GradingScale, school_id=B["school"].id)
    c = _client(gapp, login_as, A)
    page = c.get(_url(gapp, "results.scale_templates"), base_url=host(A)).get_data(as_text=True)
    assert 'name="make_default" value="1" class="w-4 h-4 accent-primary" checked' in page
    r = c.post(_url(gapp, "results.scale_template_apply", key="letter-gpa"), base_url=host(A),
               data={"make_default": "1"})
    assert r.status_code == 302
    with gapp.test_request_context(base_url=host(A)):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, A["users"]["admin"].id))
        from app.blueprints.results.routes import _gpa_and_letter_for
        gpa, letter = _gpa_and_letter_for(Decimal("91"))
        db.session.remove()
    assert letter == "A" and Decimal(str(gpa)) == Decimal("3.75")
    assert _count(gapp, GradingScale, school_id=B["school"].id) == b_before      # B untouched


def test_the_same_name_twice_is_refused(gapp, two_schools, login_as):
    from app.models import GradingScale
    A = two_schools["A"]
    c = _client(gapp, login_as, A)
    url = _url(gapp, "results.scale_template_apply", key="descriptive-primary")
    assert c.post(url, base_url=host(A)).status_code == 302
    n = _count(gapp, GradingScale, school_id=A["school"].id)
    r = c.post(url, base_url=host(A), follow_redirects=True)
    assert "يوجد سلم بنفس الاسم" in r.get_data(as_text=True)
    assert _count(gapp, GradingScale, school_id=A["school"].id) == n


# ─── components ─────────────────────────────────────────────────────

def _subjects(app, bundle, n):
    from app.extensions import db
    from app.models import Subject
    with app.app_context():
        rows = [Subject(school_id=bundle["school"].id, name=f"TplSubj-{i}") for i in range(n)]
        db.session.add_all(rows); db.session.commit()
        ids = [r.id for r in rows]
        db.session.remove()
    return ids


def test_bulk_components_create_two_per_subject_and_skip_the_busy_one(gapp, two_schools, login_as):
    from app.models import AssessmentComponent
    A = two_schools["A"]
    sids = _subjects(gapp, A, 5)
    c = _client(gapp, login_as, A)
    url = _url(gapp, "results.component_templates")
    # one subject already has a component of its own
    from app.extensions import db
    with gapp.app_context():
        db.session.add(AssessmentComponent(school_id=A["school"].id, term_id=A["term"].id,
                                           subject_id=sids[0], name="Own", max_score=Decimal(100)))
        db.session.commit(); db.session.remove()
    form = {"key": "year-20-final-80", "term_ids": [str(A["term"].id)],
            "subject_ids": [str(i) for i in sids]}
    page = c.post(url, base_url=host(A), data={**form, "action": "preview"}).get_data(as_text=True)
    assert "هيتنشأ" in page and "TplSubj-0" in page and "فيها 1 مكوّن بالفعل" in page
    assert c.post(url, base_url=host(A), data={**form, "action": "apply"}).status_code == 302
    with gapp.app_context():
        for i, sid in enumerate(sids):
            comps = AssessmentComponent.query.filter_by(school_id=A["school"].id, term_id=A["term"].id,
                                                        subject_id=sid).all()
            if i == 0:
                assert [x.name for x in comps] == ["Own"]                       # untouched
            else:
                assert sorted((x.name, int(x.max_score)) for x in comps) == [("أعمال السنة", 20), ("اختبار نهاية الفصل", 80)]
                assert all(x.source_type == "manual" and not x.auto_sync and x.rubric_id is None for x in comps)
        db.session.remove()
    # applying again creates nothing new
    n = _count(gapp, AssessmentComponent, school_id=A["school"].id)
    c.post(url, base_url=host(A), data={**form, "action": "apply"})
    assert _count(gapp, AssessmentComponent, school_id=A["school"].id) == n


def test_a_failure_midway_rolls_everything_back(gapp, two_schools, login_as, monkeypatch):
    from app.extensions import db
    from app.models import AssessmentComponent
    A = two_schools["A"]
    sids = _subjects(gapp, A, 3)
    n = _count(gapp, AssessmentComponent, school_id=A["school"].id)
    real_add, calls = db.session.add, {"n": 0}

    def flaky(obj, *a, **k):
        if isinstance(obj, AssessmentComponent):
            calls["n"] += 1
            if calls["n"] == 4:
                raise RuntimeError("boom")
        return real_add(obj, *a, **k)
    monkeypatch.setattr(db.session, "add", flaky)
    c = _client(gapp, login_as, A)
    r = c.post(_url(gapp, "results.component_templates"), base_url=host(A),
               data={"key": "year-20-final-80", "term_ids": [str(A["term"].id)],
                     "subject_ids": [str(i) for i in sids], "action": "apply"})
    assert r.status_code == 500 and calls["n"] == 4          # failed on the 4th of 6 components
    monkeypatch.setattr(db.session, "add", real_add)
    assert _count(gapp, AssessmentComponent, school_id=A["school"].id) == n


def test_a_term_of_another_school_is_refused(gapp, two_schools, login_as):
    from app.models import AssessmentComponent
    A, B = two_schools["A"], two_schools["B"]
    n = _count(gapp, AssessmentComponent, school_id=A["school"].id)
    r = _client(gapp, login_as, A).post(_url(gapp, "results.component_templates"), base_url=host(A),
                                        data={"key": "year-20-final-80", "term_ids": [str(B["term"].id)],
                                              "subject_ids": [str(A["subject"].id)], "action": "apply"})
    assert r.status_code == 404
    assert _count(gapp, AssessmentComponent, school_id=A["school"].id) == n


# ─── rubrics, pass rule, permissions ────────────────────────────────

def test_a_rubric_template_opens_for_editing_and_is_not_duplicated(gapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Rubric
    A = two_schools["A"]
    c = _client(gapp, login_as, A)
    url = _url(gapp, "results.rubric_template_apply", key="essay")
    r = c.post(url, base_url=host(A))
    assert r.status_code == 302 and "/rubrics/" in r.headers["Location"] and r.headers["Location"].endswith("/edit")
    with gapp.app_context():
        rub = Rubric.query.filter_by(school_id=A["school"].id, title="تقييم مقال").one()
        assert len(rub.criteria) == 4 and sum(cr.weight for cr in rub.criteria) == 100
        assert rub.is_template and rub.subject_id is None and rub.created_by_id == A["users"]["admin"].id
        db.session.remove()
    assert "يوجد روبريك بنفس العنوان" in c.post(url, base_url=host(A), follow_redirects=True).get_data(as_text=True)
    assert _count(gapp, Rubric, school_id=A["school"].id, title="تقييم مقال") == 1


def test_the_pass_rule_picker_fills_the_form_and_is_off_when_frozen(gapp, two_schools, login_as):
    from app.extensions import db
    from app.models import PassRule
    A = two_schools["A"]
    c = _client(gapp, login_as, A)
    page = c.get(_url(gapp, "results.settings"), base_url=host(A)).get_data(as_text=True)
    assert 'id="pass-template"' in page and 'data-method="mixed"' in page and 'data-allowed="1"' in page
    with gapp.app_context():
        rule = PassRule.query.filter_by(school_id=A["school"].id, year_id=A["year"].id).one()
        rule.is_frozen = True
        db.session.commit(); db.session.remove()
    page = c.get(_url(gapp, "results.settings"), base_url=host(A)).get_data(as_text=True)
    assert 'id="pass-template" class="h-11 px-3 rounded-xl bg-surface-container-lowest md:max-w-md" disabled' in page


def test_without_results_edit_nothing_is_applied(gapp, two_schools, login_as):
    from app.extensions import db
    from app.models import AssessmentComponent, GradingScale, Role, Rubric
    A = two_schools["A"]
    with gapp.app_context():
        role = db.session.get(Role, A["roles"]["teacher"].id)
        assert role is not None
        perms = dict(role.permissions or {})
        perms["results"] = ["view"]
        role.permissions = perms
        db.session.commit(); db.session.remove()
    before = [_count(gapp, m, school_id=A["school"].id) for m in (GradingScale, Rubric, AssessmentComponent)]
    c = _client(gapp, login_as, A, "teacher")
    assert c.get(_url(gapp, "results.scale_templates"), base_url=host(A)).status_code == 200     # view: the library
    for url, data in ((_url(gapp, "results.scale_template_apply", key="letter-gpa"), {}),
                      (_url(gapp, "results.rubric_template_apply", key="essay"), {}),
                      (_url(gapp, "results.component_templates"),
                       {"key": "year-20-final-80", "term_ids": [str(A["term"].id)],
                        "subject_ids": [str(A["subject"].id)], "action": "apply"})):
        assert c.post(url, base_url=host(A), data=data).status_code == 403, url
    assert [_count(gapp, m, school_id=A["school"].id) for m in (GradingScale, Rubric, AssessmentComponent)] == before

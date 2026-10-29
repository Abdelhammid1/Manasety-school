"""`flask lms tf-report` — READ-ONLY list of صح/خطأ questions whose correct
answer is not exactly one (ticket «صح/خطأ بإجابتين»). Nothing is changed:
the list goes to Abdelhamid, the teachers fix each question from its page
(the save now requires one answer). Prints no student data — school,
where the question lives, its id, how many choices are marked correct,
and the start of the prompt."""

import click

from . import bp
from ...extensions import db


def _rows():
    from ...models import (
        AssignmentChoice, AssignmentQuestion, BankChoice, BankQuestion, Choice,
        CourseAssignment, Course, Question, Quiz,
    )
    sources = (
        ("quiz", Question, Choice, Choice.question_id,
         lambda q: (db.session.get(Quiz, q.quiz_id), "quiz")),
        ("assignment", AssignmentQuestion, AssignmentChoice, AssignmentChoice.question_id,
         lambda q: (db.session.get(CourseAssignment, q.assignment_id), "assignment")),
        ("bank", BankQuestion, BankChoice, BankChoice.question_id, None),
    )
    for where, model, choice, fk, parent in sources:
        n_correct = (db.session.query(db.func.count(choice.id))
                     .filter(fk == model.id, choice.is_correct.is_(True))
                     .correlate(model).scalar_subquery())
        q = (db.session.query(model, n_correct).execution_options(include_deleted=True)
             .filter(model.kind == "tf", n_correct != 1))
        for row, n in q.all():
            if parent is None:
                school_id, owner = row.school_id, ""
            else:
                p, _ = parent(row)
                course = db.session.get(Course, p.course_id) if p is not None else None
                school_id = course.school_id if course is not None else None
                owner = f"{where} #{p.id} «{(p.title or '')[:40]}»" if p is not None else where
            yield school_id, where, row.id, n, owner, (row.prompt or "")[:60]


@bp.cli.command("tf-report")
@click.option("--school-id", type=int, default=None, help="one school only")
def tf_report(school_id):
    """List صح/خطأ questions with 0 or 2+ correct answers (read-only)."""
    rows = sorted((r for r in _rows() if school_id is None or r[0] == school_id),
                  key=lambda r: (r[0] or 0, r[1], r[2]))
    click.echo("school_id\twhere\tquestion_id\tcorrect_marked\towner\tprompt")
    for r in rows:
        click.echo("\t".join("" if v is None else str(v) for v in r))
    click.echo(f"# {len(rows)} question(s) — nothing was changed")

"""`flask lms tf-report` — READ-ONLY list of صح/خطأ questions whose correct
answer is not exactly one (ticket «صح/خطأ بإجابتين»). Nothing is changed:
the list goes to Abdelhamid, the teachers fix each question from its page
(the save now requires one answer). Prints no student data — school,
where the question lives, its id, how many choices are marked correct,
and the start of the prompt. Deleted questions (nobody can open them) are
left out."""

import click

from . import bp
from ...extensions import db


def _rows():
    from ...models import (
        AssignmentChoice, AssignmentQuestion, BankChoice, BankQuestion, Choice,
        CourseAssignment, Question, Quiz,
    )
    sources = (
        ("quiz", Question, Choice, Quiz, Question.quiz_id),
        ("assignment", AssignmentQuestion, AssignmentChoice, CourseAssignment, AssignmentQuestion.assignment_id),
        ("bank", BankQuestion, BankChoice, None, None),
    )
    for where, model, choice, parent, parent_fk in sources:
        n_correct = (db.session.query(db.func.count(choice.id))
                     .filter(choice.question_id == model.id, choice.is_correct.is_(True))
                     .correlate(model).scalar_subquery())
        cols = [model.school_id, model.id, n_correct, model.prompt]
        q = db.session.query(*cols)
        if parent is not None:          # the owner's title in the same query (no per-row lookups)
            q = q.add_columns(parent.id, parent.title).join(parent, parent.id == parent_fk)
        for row in q.filter(model.kind == "tf", n_correct != 1).all():
            owner = f"{where} #{row[4]} «{(row[5] or '')[:40]}»" if parent is not None else ""
            yield row[0], where, row[1], row[2], owner, (row[3] or "")[:60]


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

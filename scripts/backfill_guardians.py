"""Ticket 1 backfill — turn Student.parent_* / mother_* fields into
Guardian rows with StudentGuardian join rows. Idempotent: re-running
after a partial run merges instead of duplicating."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import Student, Guardian, StudentGuardian


def _norm(s):
    return (s or "").strip()


def _merge_key(name, phone, school_id):
    """Two guardians match when they share the same school + same name
    + same phone (either equal or both empty)."""
    return (school_id, _norm(name).casefold(), _norm(phone))


def run():
    app = create_app()
    with app.app_context():
        # index existing guardians by merge key so we don't duplicate.
        existing = {}
        for g in Guardian.query.all():
            existing[_merge_key(g.full_name, g.phone, g.school_id)] = g

        created = 0
        linked = 0
        for stu in Student.query.all():
            sid = stu.school_id
            # father
            if _norm(getattr(stu, "parent_name", None)):
                key = _merge_key(stu.parent_name, getattr(stu, "parent_phone", None), sid)
                g = existing.get(key)
                if g is None:
                    g = Guardian(
                        school_id=sid,
                        full_name=_norm(stu.parent_name),
                        phone=_norm(getattr(stu, "parent_phone", None)) or None,
                        email=_norm(getattr(stu, "parent_email", None)) or None,
                        user_id=getattr(stu, "parent_user_id", None),
                    )
                    db.session.add(g); db.session.flush()
                    existing[key] = g; created += 1
                if not any(l.guardian_id == g.id for l in stu.guardian_links):
                    db.session.add(StudentGuardian(
                        student_id=stu.id, guardian_id=g.id,
                        relationship="أب", is_primary=True,
                        is_emergency_contact=True,
                    ))
                    linked += 1

            # mother
            if _norm(getattr(stu, "mother_name", None)):
                key = _merge_key(stu.mother_name, getattr(stu, "mother_phone", None), sid)
                g = existing.get(key)
                if g is None:
                    g = Guardian(
                        school_id=sid,
                        full_name=_norm(stu.mother_name),
                        phone=_norm(getattr(stu, "mother_phone", None)) or None,
                    )
                    db.session.add(g); db.session.flush()
                    existing[key] = g; created += 1
                # Only link if not already; do not set primary (father wins
                # by default; the admin can flip in the UI later).
                if not any(l.guardian_id == g.id for l in stu.guardian_links):
                    db.session.add(StudentGuardian(
                        student_id=stu.id, guardian_id=g.id,
                        relationship="أم",
                        is_emergency_contact=True,
                    ))
                    linked += 1

        db.session.commit()
        print(f"Guardians created: {created}")
        print(f"Student↔Guardian links added: {linked}")
        print(f"Total Guardian rows now: {Guardian.query.count()}")
        print(f"Total StudentGuardian links now: {StudentGuardian.query.count()}")


if __name__ == "__main__":
    run()

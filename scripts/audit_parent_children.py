"""audit_parent_children.py — Sprint 11 diagnostic.

Lists every parent user with the students currently linked to them via
`Student.parent_user_id`. Meant for the operator to spot data mistakes such
as a classmate accidentally re-parented onto the wrong wali account (which
is the most likely explanation when a parent complains they see kids that
aren't theirs — the mobile-side query is correctly scoped to
`parent_user_id == current_user.id`).

Usage:
    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python scripts/audit_parent_children.py

Outputs a plain-text table grouped by school / parent user, no side effects.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

# Windows console defaults to cp1252 and can't print Arabic — force UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# Ensure repo root on sys.path so `app` imports work when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                       # noqa: E402
from app.extensions import db                    # noqa: E402
from app.models import School, Student, User     # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        schools = School.query.order_by(School.id).all()
        for school in schools:
            parents = (
                db.session.query(User)
                .filter(User.school_id == school.id)
                .filter(User.id.in_(
                    db.session.query(Student.parent_user_id)
                    .filter(Student.school_id == school.id,
                            Student.parent_user_id.isnot(None))
                    .distinct()
                ))
                .order_by(User.username)
                .all()
            )

            print("=" * 70)
            print(f"SCHOOL #{school.id}: {school.name}")
            print("=" * 70)
            if not parents:
                print("  (no parent users own any students)")
                continue

            grouped: dict[int, list[Student]] = defaultdict(list)
            for s in Student.query.filter(
                Student.school_id == school.id,
                Student.parent_user_id.isnot(None),
            ).all():
                grouped[s.parent_user_id].append(s)

            for parent in parents:
                kids = grouped.get(parent.id, [])
                role_name = parent.role.name if parent.role else "?"
                flag = "  ⚠ NOT PARENT ROLE" if role_name != "parent" else ""
                print(f"\n  parent user #{parent.id} — username={parent.username!r} "
                      f"(role={role_name}){flag}")
                print(f"    full_name: {parent.full_name}")
                print(f"    total students linked: {len(kids)}")
                for s in kids:
                    phone = s.parent_phone or "—"
                    print(f"      - #{s.id} {s.permanent_code}  {s.full_name}  "
                          f"(parent_phone={phone})")

            orphaned = Student.query.filter(
                Student.school_id == school.id,
                Student.parent_user_id.is_(None),
            ).count()
            print(f"\n  orphaned (parent_user_id IS NULL): {orphaned} student(s)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

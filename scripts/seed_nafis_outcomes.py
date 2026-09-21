"""Load the ETEC NAFIS learning-outcomes tree into `learning_outcomes`.

Reads `seeds/nafis_outcomes.json` and inserts rows keyed on
`(school_id=NULL, code)` so the seed is global (shared across every
tenant) and idempotent — re-running with the same JSON updates existing
rows in place instead of duplicating them.

Usage:
    python scripts/seed_nafis_outcomes.py
    # or, to also print a per-(subject,level) count summary:
    python scripts/seed_nafis_outcomes.py --stats
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

# Make the flask app importable when this file is run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app             # noqa: E402
from app.extensions import db           # noqa: E402
from app.models import LearningOutcome  # noqa: E402


SEED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "seeds", "nafis_outcomes.json",
)


def _upsert(session, *, subject, level, kind, code, seq, text_ar, parent_id):
    """Insert or update one row; matching key is (school_id NULL, code)."""
    row = None
    if code:
        row = LearningOutcome.query.filter_by(school_id=None, code=code).first()
    if row is None:
        row = LearningOutcome(
            school_id=None, subject=subject, level=level, kind=kind,
            code=code, seq=seq, text_ar=text_ar, parent_id=parent_id,
        )
        session.add(row)
    else:
        row.subject = subject
        row.level = level
        row.kind = kind
        row.seq = seq
        row.text_ar = text_ar
        row.parent_id = parent_id
    session.flush()
    return row


def _load(json_path: str, *, stats: bool = False) -> dict[str, Any]:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    counters = {}   # (subject, level) → { kind → count }

    for subj in data.get("subjects", []):
        subject_key = subj["key"]
        for lvl in subj.get("levels", []):
            level_key = lvl["level"]
            counters.setdefault((subject_key, level_key), {})
            for domain in lvl.get("domains", []):
                # domain row (kind='domain'). Code is synthesised so re-runs
                # match: subject-level-D-index.
                dom_code = None   # Domains have no ETEC code; we skip codes.
                domain_row = LearningOutcome(
                    school_id=None,
                    subject=subject_key, level=level_key,
                    kind="domain", code=None, seq=None,
                    text_ar=domain.get("name_ar", "").strip(),
                    parent_id=None,
                )
                # We ONLY insert domains via natural key (subject,level,text)
                # instead of a code — cheaper than synthesising codes and
                # avoids conflicting with real ETEC codes. Try to reuse.
                existing_dom = LearningOutcome.query.filter_by(
                    school_id=None, subject=subject_key, level=level_key,
                    kind="domain", text_ar=domain_row.text_ar,
                ).first()
                if existing_dom is None:
                    db.session.add(domain_row); db.session.flush()
                else:
                    domain_row = existing_dom
                counters[(subject_key, level_key)]["domain"] = \
                    counters[(subject_key, level_key)].get("domain", 0) + 1

                for sub in domain.get("subdomains", []):
                    sub_row = LearningOutcome.query.filter_by(
                        school_id=None, subject=subject_key, level=level_key,
                        kind="subdomain",
                        parent_id=domain_row.id,
                        text_ar=sub.get("name_ar", "").strip(),
                    ).first()
                    if sub_row is None:
                        sub_row = LearningOutcome(
                            school_id=None,
                            subject=subject_key, level=level_key,
                            kind="subdomain", code=None, seq=None,
                            text_ar=sub.get("name_ar", "").strip(),
                            parent_id=domain_row.id,
                        )
                        db.session.add(sub_row); db.session.flush()
                    counters[(subject_key, level_key)]["subdomain"] = \
                        counters[(subject_key, level_key)].get("subdomain", 0) + 1

                    for std in sub.get("standards", []):
                        std_row = _upsert(
                            db.session,
                            subject=subject_key, level=level_key,
                            kind="standard",
                            code=std.get("code"),
                            seq=None,
                            text_ar=std.get("text_ar", "").strip(),
                            parent_id=sub_row.id,
                        )
                        counters[(subject_key, level_key)]["standard"] = \
                            counters[(subject_key, level_key)].get("standard", 0) + 1

                        # Indicators — no ETEC code, natural key on text.
                        for i, ind_text in enumerate(std.get("indicators", []), start=1):
                            ind_text = (ind_text or "").strip()
                            if not ind_text:
                                continue
                            ind_row = LearningOutcome.query.filter_by(
                                school_id=None,
                                parent_id=std_row.id,
                                seq=i,
                            ).first()
                            if ind_row is None:
                                ind_row = LearningOutcome(
                                    school_id=None,
                                    subject=subject_key, level=level_key,
                                    kind="indicator", code=None, seq=i,
                                    text_ar=ind_text, parent_id=std_row.id,
                                )
                                db.session.add(ind_row)
                            else:
                                ind_row.text_ar = ind_text
                            counters[(subject_key, level_key)]["indicator"] = \
                                counters[(subject_key, level_key)].get("indicator", 0) + 1

            # Broad outcomes as a shallow root band per level — helpful for
            # UI headers even though they don't get referenced by scores.
            for bo in lvl.get("broad_outcomes", []):
                key = f"BROAD:{subject_key}:{level_key}:{bo.get('seq')}"
                row = LearningOutcome.query.filter_by(
                    school_id=None, code=key,
                ).first()
                if row is None:
                    row = LearningOutcome(
                        school_id=None,
                        subject=subject_key, level=level_key,
                        kind="broad_outcome", code=key,
                        seq=bo.get("seq"),
                        text_ar=bo.get("text_ar", "").strip(),
                    )
                    db.session.add(row)
                else:
                    row.text_ar = bo.get("text_ar", "").strip()

    db.session.commit()
    if stats:
        print("Per (subject, level) row counts:")
        for (subj, lvl), kinds in sorted(counters.items()):
            print(f"  {subj:8s} {lvl}: " +
                  ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    return counters


def main():
    stats = ("--stats" in sys.argv)
    app = create_app()
    with app.app_context():
        counters = _load(SEED_PATH, stats=stats)
    total = sum(v for kinds in counters.values() for v in kinds.values())
    print(f"seeded / refreshed {total} learning_outcomes rows "
          f"across {len(counters)} (subject, level) combos.")


if __name__ == "__main__":
    main()

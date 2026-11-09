"""Journal entries get a sequential per-school number automatically."""
from datetime import date


def test_entry_no_sequential_per_school(app):
    from app.extensions import db
    from app.models import JournalEntry
    with app.app_context():
        a = [JournalEntry(school_id=90001, entry_date=date.today(), description=f"t{i}")
             for i in range(3)]
        b = JournalEntry(school_id=90002, entry_date=date.today(), description="other")
        db.session.add_all(a + [b])
        db.session.flush()
        assert [e.entry_no for e in a] == [1, 2, 3]
        assert b.entry_no == 1
        c = JournalEntry(school_id=90001, entry_date=date.today(), description="later")
        db.session.add(c)
        db.session.flush()
        assert c.entry_no == 4
        db.session.rollback()

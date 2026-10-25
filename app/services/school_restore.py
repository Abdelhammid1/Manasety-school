"""SAAS-048 — restore a school from a package, whole or by module, safely.

    preview(...)   -> what each chosen module would do (nothing is written)
    run(...)       -> restore point -> maintenance (this school only) ->
                      ONE transaction -> integrity checks -> commit, or a
                      full rollback with a clear reason

Safety rules (ticket, shared section):
  * the package is verified first (school_backup.verify_package): one row
    of another school, a bad checksum, an unknown table / column or a newer
    schema refuses it whole; its school must be THIS school;
  * writes use the schema's own column lists (never names from the file)
    through SQLAlchemy Core — no SQL built from the package's text;
  * never restored: the schools row's plan / state / slug / SMTP fields,
    platform tables, sessions, audit_logs; users only when "accounts" is
    chosen explicitly, and the admin running the restore (row, role,
    scopes) and platform support accounts are never touched;
  * replace mode deletes the chosen modules' rows and inserts the
    package's; add_missing inserts only rows whose primary key is absent;
  * modules, not tables: a module's required parents (NOT NULL foreign
    keys into another module) are added automatically, with the reason;
    an optional link whose row is gone becomes NULL (counted);
  * after the writes: no orphan foreign key, tenant integrity clean,
    every journal entry balanced — or everything is rolled back.

Foreign keys are DEFERRABLE INITIALLY IMMEDIATE (migration c4d6f8a0b2c4);
only this transaction defers them, so re-inserting the rows a delete just
removed doesn't trip a constraint midway. They're checked before commit.
"""
from __future__ import annotations

import io
import json
import secrets
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

import sqlalchemy as sa

from ..extensions import db
from . import school_backup as engine


class RestoreError(Exception):
    """A restore that can't go ahead (or was rolled back); safe to show."""


# ─── modules ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Module:
    key: str
    label: str
    tables: tuple[str, ...]
    file_kinds: tuple[str, ...] = ()
    explicit_only: bool = False          # never added as a dependency


MODULES: tuple[Module, ...] = (
    Module("settings", "إعدادات المدرسة", (), ("logo",)),
    Module("academic", "الأساسيات الأكاديمية", (
        "academic_years", "terms", "grades", "sections", "subjects", "subject_grades", "subject_terms",
        "subject_prerequisites", "calendar_days", "pass_rules", "teachers", "teacher_subjects",
        "assignments")),
    Module("students", "الطلاب وأولياء الأمور", (
        "students", "guardians", "student_guardians", "student_tags", "student_tag_links",
        "student_documents", "student_notes", "student_health_profiles", "health_incidents",
        "student_previous_schools", "enrollments", "transfer_logs", "behavior_categories",
        "behavior_incidents", "behavior_actions", "pickup_calls", "student_risk_scores"),
        ("student_photo", "previous_school", "student_docs")),
    Module("attendance", "الحضور", ("attendance", "attendance_rules", "attendance_rule_triggers"),
           ("excuse",)),
    Module("lms", "الـ LMS", ("passages", "materials", "axes", "indicators", "rubrics", "rubric_criteria",
                             "rubric_scores"), ("materials", "lessons", "submissions")),
    Module("results", "الدرجات والنتائج", (
        "assessment_components", "grade_entries", "year_results", "grading_scales",
        "grading_scale_levels", "transcript_snapshots", "nafis_cycles", "nafis_results",
        "nafis_outcome_scores", "learning_outcomes", "student_gaps", "intervention_plans",
        "intervention_plan_outcomes", "intervention_sessions")),
    Module("schedule", "الجدول", ("days", "periods", "schedule_slots", "rooms", "substitutions")),
    Module("finance", "المالية والمحاسبة", (
        "accounts", "journal_entries", "journal_lines", "invoices", "invoice_lines", "installments",
        "payments", "fee_types", "discount_types", "student_discounts", "receipt_vouchers",
        "refund_requests", "expenses", "vendors", "payment_methods", "cost_centers", "budgets",
        "bank_statement_lines", "petty_cash_transactions", "recurring_fee_schedules",
        "recurring_invoice_log")),
    Module("hr", "الموارد البشرية", (
        "employees", "payrolls", "payroll_settlements", "employee_advances", "leave_balances",
        "leave_requests", "staff_attendance")),
    Module("messaging", "الرسائل والإعلانات", (
        "conversations", "conversation_participants", "messages", "notification_logs",
        "notification_preferences"), ("messages",)),
    Module("accounts", "الحسابات (المستخدمون والصلاحيات)", ("users", "roles", "user_scopes"),
           explicit_only=True),
)
# Backed up for the record, never written back by a restore.
NEVER_RESTORED: dict[str, str] = {
    "audit_logs": "the audit trail is append-only history",
    "import_batches": "a log of past imports, not school data",
}
MODULE_BY_KEY = {m.key: m for m in MODULES}


def module_of_table() -> dict[str, str]:
    out = {}
    for m in MODULES:
        for t in m.tables:
            out[t] = m.key
    for t in engine.backup_tables():
        if t.name.startswith("lms_"):
            out.setdefault(t.name, "lms")
    return out


def tables_of(module_key: str) -> list[str]:
    owned = module_of_table()
    return [t for t, k in owned.items() if k == module_key]


def unmapped_tables() -> list[str]:
    """Backed-up tables in no module and not NEVER_RESTORED (coverage test)."""
    owned = module_of_table()
    return sorted(t.name for t in engine.backup_tables()
                  if t.name not in owned and t.name not in NEVER_RESTORED)


def _tables_by_name() -> dict[str, sa.Table]:
    return {t.name: t for t in engine.backup_tables()}


def hard_dependencies() -> dict[str, dict[str, list[str]]]:
    """{module: {needed module: [table.column, ...]}} from NOT NULL foreign
    keys that cross modules (accounts never: users are explicit-only)."""
    owned = module_of_table()
    out: dict[str, dict[str, list[str]]] = {}
    for name, t in _tables_by_name().items():
        m = owned.get(name)
        if not m:
            continue
        for fk in t.foreign_keys:
            p = owned.get(fk.column.table.name)
            if not p or p == m or MODULE_BY_KEY[p].explicit_only or fk.parent.nullable:
                continue
            out.setdefault(m, {}).setdefault(p, []).append(f"{name}.{fk.parent.name}")
    return out


def with_dependencies(chosen: Iterable[str]) -> tuple[list[str], dict[str, str]]:
    """The chosen modules + every module they need; {added: reason}."""
    unknown = [k for k in chosen if k not in MODULE_BY_KEY]
    if unknown:
        raise RestoreError(f"وحدة غير معروفة: {', '.join(unknown)}")
    deps = hard_dependencies()
    selected, added = list(dict.fromkeys(chosen)), {}
    i = 0
    while i < len(selected):
        for need, cols in deps.get(selected[i], {}).items():
            if need not in selected:
                selected.append(need)
                added[need] = (f"«{MODULE_BY_KEY[selected[i]].label}» تعتمد عليها "
                               f"({cols[0]})")
        i += 1
    order = [m.key for m in MODULES if m.key in selected]
    return order, added


# ─── reading a package ──────────────────────────────────────────────

def _convert(col: sa.Column, raw: Optional[str]):
    if raw is None:
        return None
    t = col.type
    try:
        if isinstance(t, sa.Boolean):
            return raw == "t"
        if isinstance(t, (sa.Integer, sa.BigInteger, sa.SmallInteger)):
            return int(raw)
        if isinstance(t, sa.Float):
            return float(raw)
        if isinstance(t, sa.Numeric):
            return Decimal(raw)
        if isinstance(t, sa.DateTime):
            return datetime.fromisoformat(raw)
        if isinstance(t, sa.Date):
            return date.fromisoformat(raw)
        if isinstance(t, sa.Time):
            return time.fromisoformat(raw)
        if isinstance(t, sa.JSON):
            return json.loads(raw)
        if isinstance(t, sa.LargeBinary):
            return bytes.fromhex(raw[2:] if raw.startswith("\\x") else raw)
    except (ValueError, TypeError):
        raise RestoreError(f"قيمة غير صالحة في {col.table.name}.{col.name}") from None
    return raw


class Package:
    """A verified, decrypted package opened for reading."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._tar = tarfile.open(self.path, mode="r:gz")
        members = {m.name: m for m in self._tar.getmembers()}
        self._members = members
        self.manifest = json.loads(self._tar.extractfile(members["manifest.json"]).read())
        self.school = json.loads(self._tar.extractfile(members["school.json"]).read())

    def close(self):
        self._tar.close()

    def rows(self, table: sa.Table) -> list[dict]:
        meta = (self.manifest.get("tables") or {}).get(table.name)
        if not meta:
            return []
        cols = [table.c[c] for c in meta["columns"]]
        raw = self._tar.extractfile(self._members[f"data/{table.name}.copy"])
        out = []
        # streamed line by line (the package's unpacked size is capped at verify)
        for line in io.TextIOWrapper(raw, encoding="utf-8", newline="\n"):
            vals = engine.parse_copy_line(line)
            out.append({c.name: _convert(c, v) for c, v in zip(cols, vals)})
        return out

    def files(self, kinds: Iterable[str]) -> list[tuple[str, tarfile.TarInfo]]:
        kinds = set(kinds)
        out = []
        for name, m in self._members.items():
            if name.startswith("files/"):
                rel = name[len("files/"):]
                if rel.split("/", 1)[0] in kinds:
                    out.append((rel, m))
        return out

    def extract_to(self, member: tarfile.TarInfo, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._tar.extractfile(member) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)


def open_verified(path, school_id: int) -> Package:
    rep = engine.verify_package(path, expect_school_id=school_id)
    if not rep.ok:
        raise RestoreError("الحزمة مرفوضة: " + "؛ ".join(rep.problems[:3]))
    return Package(path)


# ─── what may be touched ────────────────────────────────────────────

@dataclass
class Protected:
    """Rows a restore never deletes or overwrites."""
    user_ids: set = field(default_factory=set)
    role_ids: set = field(default_factory=set)

    @classmethod
    def for_actor(cls, conn, school_id: int, actor_user_id: Optional[int]) -> "Protected":
        users = sa.table("users", sa.column("id"), sa.column("school_id"), sa.column("role_id"),
                         sa.column("is_platform_support"))
        p = cls()
        for uid, rid, support in conn.execute(sa.select(users.c.id, users.c.role_id,
                                                        users.c.is_platform_support)
                                              .where(users.c.school_id == school_id)):
            if support or uid == actor_user_id:
                p.user_ids.add(uid)
                if uid == actor_user_id and rid is not None:
                    p.role_ids.add(rid)
        return p

    def keeps(self, table: str, row: dict) -> bool:
        if table == "users":
            return row.get("id") in self.user_ids
        if table == "roles":
            return row.get("id") in self.role_ids
        if table == "user_scopes":
            return row.get("user_id") in self.user_ids
        return False


def _pk(table: sa.Table) -> list[sa.Column]:
    return list(table.primary_key.columns)


def _key(table: sa.Table, row) -> tuple:
    return tuple(row[c.name] for c in _pk(table))


def _live(conn, table: sa.Table, school_id: int) -> dict[tuple, dict]:
    rows = conn.execute(sa.select(table).where(table.c.school_id == school_id)).mappings()
    return {_key(table, r): dict(r) for r in rows}


# ─── preview ────────────────────────────────────────────────────────

def preview(pkg: Package, school_id: int, chosen: Iterable[str], mode: str,
            actor_user_id: Optional[int] = None) -> dict:
    """Per module: live rows vs the package's, and what the mode would do.
    `blockers` must be empty for run() to go ahead. Writes nothing."""
    if mode not in ("replace", "add_missing"):
        raise RestoreError("وضع غير معروف.")
    modules, added = with_dependencies(chosen)
    tables = _tables_by_name()
    owned = module_of_table()
    selected = {t for t, m in owned.items() if m in modules}
    conn = db.session.connection()
    protect = Protected.for_actor(conn, school_id, actor_user_id)
    out = {"mode": mode, "modules": [], "added": added, "blockers": [], "notes": []}
    for key in modules:
        mod = MODULE_BY_KEY[key]
        rows = []
        for name in tables_of(key):
            t = tables[name]
            live = _live(conn, t, school_id)
            pkg_rows = pkg.rows(t)
            pkg_keys = {_key(t, r) for r in pkg_rows}
            inserted = sum(1 for k in pkg_keys if k not in live)
            if mode == "replace":
                kept = sum(1 for r in live.values() if protect.keeps(name, r))
                deleted = sum(1 for k, r in live.items() if k not in pkg_keys and not protect.keeps(name, r))
                updated = len(pkg_keys & set(live)) - kept
            else:
                deleted, updated = 0, 0
                kept = len(pkg_keys & set(live))
            rows.append({"table": name, "live": len(live), "package": len(pkg_rows),
                         "insert": inserted, "update": max(updated, 0), "delete": deleted, "keep": kept})
            _collisions(conn, t, school_id, pkg_rows, out["blockers"])
            if mode == "replace":
                _still_used(conn, t, school_id, live, pkg_keys, selected, owned, out["blockers"])
        files = len(pkg.files(mod.file_kinds))
        out["modules"].append({"key": key, "label": mod.label, "tables": rows, "files": files,
                               "added_reason": added.get(key)})
    if "accounts" in modules:
        out["notes"].append("حسابك وصلاحياتك وحسابات الدعم ما بتتأثرش. الحسابات الجديدة "
                            "بترجع من غير كلمة مرور (لازم إعادة تعيين).")
    return out


def _collisions(conn, t: sa.Table, school_id: int, pkg_rows: list[dict], blockers: list) -> None:
    """A package id that exists in ANOTHER school's row: refuse."""
    if "id" not in t.c or not pkg_rows:
        return
    ids = [r["id"] for r in pkg_rows if r.get("id") is not None]
    for i in range(0, len(ids), 500):
        n = conn.execute(sa.select(sa.func.count()).select_from(t)
                         .where(t.c.id.in_(ids[i:i + 500]), t.c.school_id != school_id)).scalar()
        if n:
            blockers.append(f"{t.name}: {n} رقم في الحزمة مستخدم لمدرسة أخرى")
            return


def _still_used(conn, t: sa.Table, school_id: int, live: dict, pkg_keys: set,
                selected: set, owned: dict, blockers: list) -> None:
    """Replace would delete rows a NOT chosen module still points at."""
    gone = [k[0] for k in live if k not in pkg_keys and len(k) == 1]
    if not gone:
        return
    for child in engine.backup_tables():
        if child.name in selected or child.name in NEVER_RESTORED:
            continue
        for fk in child.foreign_keys:
            if fk.column.table.name != t.name or fk.parent.nullable:
                continue
            n = 0
            for i in range(0, len(gone), 500):
                n += conn.execute(sa.select(sa.func.count()).select_from(child)
                                  .where(fk.parent.in_(gone[i:i + 500]))).scalar()
            if n:
                need = MODULE_BY_KEY[owned[child.name]].label if child.name in owned else child.name
                blockers.append(f"حذف {t.name} هيكسر {n} صف في «{need}» — اختارها كمان")


# ─── run ────────────────────────────────────────────────────────────

def _unusable_secret(col: sa.Column, cache: dict):
    if col.name not in cache:
        if col.name == "password_hash":
            from ..extensions import bcrypt
            cache[col.name] = bcrypt.generate_password_hash(secrets.token_urlsafe(32)).decode()
        else:
            cache[col.name] = secrets.token_urlsafe(32)
    return cache[col.name]


@dataclass
class RunReport:
    modules: list
    inserted: dict = field(default_factory=dict)
    deleted: dict = field(default_factory=dict)
    updated: dict = field(default_factory=dict)
    nulled: dict = field(default_factory=dict)
    skipped: dict = field(default_factory=dict)
    files: int = 0

    def as_dict(self):
        return {k: getattr(self, k) for k in ("modules", "inserted", "deleted", "updated", "nulled",
                                               "skipped", "files")}


def apply(pkg: Package, school_id: int, chosen: Iterable[str], mode: str,
          actor_user_id: Optional[int] = None, *, fail_after: Optional[str] = None) -> RunReport:
    """Write the package into THIS school inside the caller's transaction
    (db.session). Raises RestoreError — the caller rolls back.
    `fail_after` (tests only) raises right after that table is written."""
    plan = preview(pkg, school_id, chosen, mode, actor_user_id)
    if plan["blockers"]:
        raise RestoreError("مش ممكن الاسترجاع: " + "؛ ".join(plan["blockers"][:3]))
    modules = [m["key"] for m in plan["modules"]]
    tables = _tables_by_name()
    owned = module_of_table()
    names = [t.name for t in db.metadata.sorted_tables
             if t.name in tables and owned.get(t.name) in modules]          # parents first
    selected = set(names)
    conn = db.session.connection()
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    protect = Protected.for_actor(conn, school_id, actor_user_id)
    rep = RunReport(modules=modules)
    secret_cache: dict = {}
    from .audit import is_secret_field
    live_secrets: dict[str, dict] = {}       # replace: secrets of rows deleted, by key

    # 1. delete (replace) — children first; keep protected rows
    if mode == "replace":
        for name in reversed(names):
            t = tables[name]
            secret_cols = [c for c in t.c if is_secret_field(c.name)]
            live = _live(conn, t, school_id)
            if secret_cols:
                live_secrets[name] = {k: {c.name: r[c.name] for c in secret_cols} for k, r in live.items()}
            doomed = [k for k, r in live.items() if not protect.keeps(name, r)]
            pk = _pk(t)
            for i in range(0, len(doomed), 500):
                part = doomed[i:i + 500]
                if len(pk) == 1:
                    cond = pk[0].in_([k[0] for k in part])
                else:
                    cond = sa.or_(*[sa.and_(*[c == v for c, v in zip(pk, k)]) for k in part])
                conn.execute(t.delete().where(cond, t.c.school_id == school_id))
            rep.deleted[name] = len(doomed)

    # 2. insert — parents first. After a replace's delete only protected
    # rows are left: their package rows are skipped (kept as they are).
    for name in names:
        t = tables[name]
        live_keys = set(_live(conn, t, school_id))
        rows, nulled, skipped = [], 0, 0
        for r in pkg.rows(t):
            k = _key(t, r)
            if k in live_keys or protect.keeps(name, r):
                skipped += 1
                continue
            row = _with_secrets(t, k, dict(r), live_secrets.get(name, {}), secret_cache)
            if name == "users" and "is_platform_support" in t.c:
                row["is_platform_support"] = False     # only the platform makes support accounts
            row, n_null, ok = _resolve_links(conn, t, row, selected)
            nulled += n_null
            if ok:
                rows.append(row)
            else:
                skipped += 1
        done, clashes = _insert(conn, t, rows)
        rep.inserted[name] = done
        if nulled:
            rep.nulled[name] = nulled
        if skipped + clashes:
            rep.skipped[name] = skipped + clashes
        if fail_after == name:
            raise RestoreError(f"فشل متعمّد بعد {name} (اختبار)")

    # 3. school settings (whitelisted columns of the school's own row)
    if "settings" in modules:
        schools = db.metadata.tables["schools"]
        values = {k: _school_value(schools.c[k], v) for k, v in pkg.school.items()
                  if k in engine.SCHOOL_ROW_RESTORABLE and k in schools.c
                  and k not in engine.SCHOOL_ROW_EXCLUDED}
        # a logo is only ever this school's own stored file
        if values.get("logo_url") and not str(values["logo_url"]).startswith(f"/files/{int(school_id)}/"):
            values.pop("logo_url")
        # a colour reaches pages as CSS: only a strict #RRGGBB, else none
        if "primary_color" in values:
            from .branding import normalize_hex
            values["primary_color"] = normalize_hex(values["primary_color"])
        conn.execute(schools.update().where(schools.c.id == school_id).values(**values))
        rep.updated["schools"] = 1

    if conn.dialect.name == "postgresql":
        try:
            conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
        except sa.exc.IntegrityError:
            raise RestoreError("الاسترجاع كان هيكسر روابط بين البيانات — اتلغى.") from None
    _check(conn, school_id, selected, "finance" in modules)
    _fix_sequences(conn, [tables[n] for n in names])
    return rep


def _with_secrets(t: sa.Table, k: tuple, row: dict, kept: dict, cache: dict) -> dict:
    """Secret columns never travel: a row that existed keeps its own
    value, a new one gets an unusable value (a reset is needed)."""
    from .audit import is_secret_field
    for c in t.c:
        if c.name in row or not is_secret_field(c.name):
            continue
        prev = kept.get(k, {}).get(c.name)
        if prev is not None:
            row[c.name] = prev
        elif not c.nullable:
            row[c.name] = _unusable_secret(c, cache)
    return row


def _resolve_links(conn, t: sa.Table, row: dict, selected: set) -> tuple[dict, int, bool]:
    """A link into a table this restore doesn't write must point at an
    existing row: optional → NULL when it's gone, required → skip the row."""
    nulled = 0
    for fk in t.foreign_keys:
        parent = fk.column.table
        v = row.get(fk.parent.name)
        if v is None or parent.name in selected:
            continue
        if conn.execute(sa.select(sa.literal(1)).select_from(parent).where(fk.column == v)).first():
            continue
        if not fk.parent.nullable:
            return row, nulled, False
        row[fk.parent.name] = None
        nulled += 1
    return row, nulled, True


def _insert(conn, t: sa.Table, rows: list[dict]) -> tuple[int, int]:
    """Insert in one batch; if a unique key clashes (add_missing next to
    newer rows), retry row by row in savepoints and skip the clashing ones."""
    if not rows:
        return 0, 0
    try:
        with conn.begin_nested():
            conn.execute(t.insert(), rows)
        return len(rows), 0
    except sa.exc.IntegrityError:
        pass
    done = clashes = 0
    for row in rows:
        try:
            with conn.begin_nested():
                conn.execute(t.insert(), [row])
            done += 1
        except sa.exc.IntegrityError:
            clashes += 1
    return done, clashes


def _school_value(col: sa.Column, v):
    if v is None or isinstance(v, bool) or (isinstance(v, int) and not isinstance(col.type, sa.Numeric)):
        return v
    return _convert(col, v if isinstance(v, str) else str(v))


def _check(conn, school_id: int, selected: set, finance: bool) -> None:
    """Orphan FKs (every edge into or out of a restored table), tenant
    integrity, balanced journal entries. Raises RestoreError."""
    problems = []
    # This school's rows only: another school's old data never blocks it.
    for t in engine.backup_tables():
        for fk in t.foreign_keys:
            if t.name not in selected and fk.column.table.name not in selected:
                continue
            parent = fk.column.table
            # aliased: in a self-reference (accounts.parent_id → accounts) the
            # subquery would otherwise correlate to the outer row and compare
            # each row with itself — every child account an "orphan"
            p = parent.alias("p")
            n = conn.execute(sa.select(sa.func.count()).select_from(t)
                             .where(t.c.school_id == school_id, fk.parent.isnot(None),
                                    ~sa.exists().where(p.c[fk.column.name] == fk.parent))).scalar()
            if n:
                problems.append(f"{t.name}.{fk.parent.name} → {parent.name}: {n}")
    from .tenant_guard import edges
    for e in edges():
        child = db.metadata.tables[e.child].alias("c")
        parent = db.metadata.tables[e.parent].alias("p")          # aliases: self-references
        col = child.c[e.column]
        n = conn.execute(sa.select(sa.func.count()).select_from(child.join(parent, parent.c.id == col))
                         .where(sa.or_(child.c.school_id == school_id, parent.c.school_id == school_id),
                                child.c.school_id != parent.c.school_id)).scalar()
        if n:
            problems.append(f"روابط بين مدرستين: {e.child}.{e.column}")
    if finance:
        lines = db.metadata.tables["journal_lines"]
        unbalanced = conn.execute(
            sa.select(lines.c.entry_id).where(lines.c.school_id == school_id)
            .group_by(lines.c.entry_id)
            .having(sa.func.coalesce(sa.func.sum(lines.c.debit), 0)
                    != sa.func.coalesce(sa.func.sum(lines.c.credit), 0))).first()
        if unbalanced:
            problems.append("قيود محاسبية غير متوازنة")
    if problems:
        raise RestoreError("فحص السلامة فشل — اتعمل rollback: " + "؛ ".join(problems[:4]))


def _fix_sequences(conn, tables: list) -> None:
    if conn.dialect.name != "postgresql":
        return
    for t in tables:
        if "id" not in t.c or not isinstance(t.c.id.type, sa.Integer):
            continue
        seq = conn.execute(sa.text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": t.name}).scalar()
        if seq:
            conn.execute(sa.text(f"SELECT setval('{seq}', GREATEST((SELECT COALESCE(MAX(id), 1) FROM "
                                 f"{t.name}), (SELECT last_value FROM {seq})))"))


# ─── files ──────────────────────────────────────────────────────────

class FileSwap:
    """Put the package's files of the restored modules in place, after
    the database checks passed and before commit; undo() if the commit
    then fails. Replace mode moves the current files aside first."""

    def __init__(self, pkg: Package, school_id: int, kinds: Iterable[str], mode: str):
        from .file_storage import upload_root
        self.pkg, self.mode, self.kinds = pkg, mode, sorted(set(kinds))
        self.root = Path(upload_root()) / str(int(school_id))
        self.aside = Path(tempfile.mkdtemp(prefix="mnst-restore-aside-", dir=engine.backups_root()))
        self.added: list[Path] = []
        self.count = 0

    def apply(self) -> int:
        for kind in self.kinds:
            cur = self.root / kind
            if self.mode == "replace" and cur.exists():
                shutil.move(str(cur), str(self.aside / kind))
        for rel, member in self.pkg.files(self.kinds):
            dest = self.root / rel
            if not dest.resolve().is_relative_to(self.root.resolve()):
                continue
            if dest.exists():
                continue                                   # add_missing keeps newer files
            self.pkg.extract_to(member, dest)
            self.added.append(dest)
            self.count += 1
        return self.count

    def undo(self) -> None:
        for p in self.added:
            p.unlink(missing_ok=True)
        for kind in self.kinds:
            moved = self.aside / kind
            if moved.exists():
                shutil.rmtree(self.root / kind, ignore_errors=True)
                shutil.move(str(moved), str(self.root / kind))

    def done(self) -> None:
        shutil.rmtree(self.aside, ignore_errors=True)


# ─── maintenance (this school only) ─────────────────────────────────

MAINTENANCE_KEY = "school_maintenance"


def _maintenance_set(school_id: int, on: bool) -> None:
    """Committed on its own connection so every other request sees it at
    once (the restore's transaction is still open)."""
    settings = db.metadata.tables["platform_settings"]
    with db.engine.begin() as c:
        row = c.execute(sa.select(settings.c.value).where(settings.c.key == MAINTENANCE_KEY)).first()
        data = json.loads(row[0]) if row and row[0] else {}
        if on:
            data[str(int(school_id))] = datetime.now(timezone.utc).isoformat()
        else:
            data.pop(str(int(school_id)), None)
        if row is None:
            c.execute(settings.insert().values(key=MAINTENANCE_KEY, value=json.dumps(data)))
        else:
            c.execute(settings.update().where(settings.c.key == MAINTENANCE_KEY)
                      .values(value=json.dumps(data)))


def in_maintenance(school_id: int, settings: Optional[dict] = None) -> bool:
    """`settings`: the request's cached platform settings (the resolver
    already read them) — so the gate costs no query on every request."""
    if settings is None:
        from .subscriptions import get_settings
        settings = get_settings()
    raw = settings.get(MAINTENANCE_KEY)
    if not raw:
        return False
    try:
        return str(int(school_id)) in json.loads(raw)
    except (ValueError, TypeError):
        return False


# ─── the whole operation ────────────────────────────────────────────

def run_restore(school_id: int, package_path, chosen: Iterable[str], mode: str, *,
                actor_user_id: Optional[int] = None, take_restore_point: bool = True,
                fail_after: Optional[str] = None) -> dict:
    """restore point → maintenance → one transaction (writes + checks +
    files) → commit, or rollback everything. Returns the report dict with
    `restore_point_backup_id`."""
    from ..models import SchoolBackup
    pkg = open_verified(package_path, school_id)
    rp_id = None
    try:
        if take_restore_point:
            res = engine.export_school(school_id)
            rp = SchoolBackup(school_id=school_id, kind="restore_point", status="succeeded", progress=100,
                              file_name=res.path.name, size_bytes=res.bytes,
                              requested_by_user_id=actor_user_id,
                              finished_at=datetime.now(timezone.utc))
            db.session.add(rp)
            db.session.commit()
            rp_id = rp.id
        _maintenance_set(school_id, True)
        swap = None
        try:
            rep = apply(pkg, school_id, chosen, mode, actor_user_id, fail_after=fail_after)
            kinds = [k for m in rep.modules for k in MODULE_BY_KEY[m].file_kinds]
            swap = FileSwap(pkg, school_id, kinds, mode)
            rep.files = swap.apply()
            db.session.commit()
        except BaseException:
            db.session.rollback()
            if swap is not None:
                swap.undo()
            raise
        finally:
            if swap is not None:
                swap.done()
            _maintenance_set(school_id, False)
        out = rep.as_dict()
        out["restore_point_backup_id"] = rp_id
        return out
    finally:
        pkg.close()


# ─── requests: create → preview → confirm → run (+ undo) ────────────

STAGE_DIR = "restore"


def _stage_dir(school_id: int) -> Path:
    d = engine.backups_dir(school_id) / STAGE_DIR
    d.mkdir(exist_ok=True)
    return d


def package_path(r) -> Optional[Path]:
    """The request's package, confined to the school's backup folder."""
    name = r.package_file or ""
    base = engine.backups_dir(r.school_id)
    p = (base / name).resolve()
    if not name or not p.is_relative_to(base.resolve()) or not p.is_file():
        return None
    return p


def _audit(action: str, r, user=None, **meta) -> None:
    from flask import has_request_context, request
    from ..models import AuditLog
    assert len(action) <= 16, action          # audit_logs.action is VARCHAR(16)
    ip = ua = None
    if has_request_context():
        ip = request.remote_addr
        ua = (request.headers.get("User-Agent") or "")[:255] or None
    db.session.add(AuditLog(
        school_id=r.school_id, user_id=getattr(user, "id", None), action=action,
        entity_type="SchoolRestore", entity_id=r.id,
        new_value={"status": r.status, "mode": r.mode, "modules": r.modules,
                   "source_backup_id": r.source_backup_id, "reason": r.reason, **meta},
        ip_address=ip, user_agent=ua))


def _open_request_guard(school_id: int) -> None:
    from ..models import SchoolRestore
    busy = SchoolRestore.query.filter(
        SchoolRestore.school_id == school_id,
        SchoolRestore.status.in_(("pending_preview", "previewing", "confirmed", "running"))).first()
    if busy:
        raise RestoreError("فيه استرجاع لسه شغال أو مستني — كمّله أو استنى يخلص.")


def create_from_backup(school_id: int, backup, *, user=None, platform_user=None, reason=None):
    from ..models import SchoolRestore
    if backup.school_id != school_id or backup.status != "succeeded" or not backup.file_name:
        raise RestoreError("النسخة دي مش متاحة للاسترجاع.")
    _open_request_guard(school_id)
    r = SchoolRestore(school_id=school_id, status="pending_preview", source_backup_id=backup.id,
                      package_file=backup.file_name, requested_by_user_id=getattr(user, "id", None),
                      platform_user_id=getattr(platform_user, "id", None), reason=reason)
    db.session.add(r)
    db.session.flush()
    _audit("restore_request", r, user, platform_user_id=getattr(platform_user, "id", None))
    db.session.commit()
    return r


def create_from_upload(school_id: int, upload, passphrase: str, *, user=None):
    """Store the uploaded package (decrypted with the passphrase, which is
    then dropped) in the school's private restore folder, and verify it
    belongs to this school before anything else happens."""
    from ..models import SchoolRestore
    _open_request_guard(school_id)
    stage = _stage_dir(school_id)
    raw = stage / f"upload-{secrets.token_hex(8)}.bin"
    upload.save(str(raw))
    plain = stage / f"upload-{secrets.token_hex(8)}.tar.gz"
    try:
        if raw.stat().st_size > engine.max_bytes():
            raise RestoreError("حجم الملف أكبر من الحد المسموح.")
        if engine.is_encrypted(raw):
            try:
                engine.decrypt_file(raw, plain, passphrase or "")
            except engine.BackupError as e:
                raise RestoreError(str(e)) from None
        else:
            shutil.copyfile(raw, plain)
    finally:
        raw.unlink(missing_ok=True)
    rep = engine.verify_package(plain, expect_school_id=school_id)
    if not rep.ok:
        plain.unlink(missing_ok=True)
        raise RestoreError("الحزمة مرفوضة: " + "؛ ".join(rep.problems[:3]))
    r = SchoolRestore(school_id=school_id, status="pending_preview",
                      package_file=f"{STAGE_DIR}/{plain.name}", requested_by_user_id=getattr(user, "id", None))
    db.session.add(r)
    db.session.flush()
    _audit("restore_uploaded", r, user)
    db.session.commit()
    return r


def run_preview(r) -> None:
    """Server CLI: numbers for every module (replace mode), for the page."""
    r.status = "previewing"
    db.session.commit()
    path = package_path(r)
    try:
        if path is None:
            raise RestoreError("ملف الحزمة غير موجود.")
        pkg = open_verified(path, r.school_id)
        try:
            all_modules = [m.key for m in MODULES]
            r.preview = {**preview(pkg, r.school_id, all_modules, "replace", r.requested_by_user_id),
                         "created_at": pkg.manifest.get("created_at")}
        finally:
            pkg.close()
        r.status = "previewed"
    except RestoreError as e:
        db.session.rollback()
        r.status, r.error = "failed", str(e)[:255]
    db.session.commit()


def _check_password(r, user, password) -> None:
    """The admin's own password, with the login lockout."""
    from datetime import timedelta
    from flask import current_app
    if user.is_locked():
        raise RestoreError("الحساب مقفول مؤقتًا بعد محاولات فاشلة — حاول لاحقًا.")
    if not password or not user.check_password(password):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= current_app.config["LOCKOUT_MAX_ATTEMPTS"]:
            user.locked_until = datetime.utcnow() + timedelta(minutes=current_app.config["LOCKOUT_MINUTES"])
            user.failed_attempts = 0
        _audit("restore_denied", r, user, refused="wrong password")
        db.session.commit()
        raise RestoreError("كلمة مرور الحساب غير صحيحة.")
    user.failed_attempts = 0


def confirm(r, *, modules: list, mode: str, typed_name: str, user=None, password: Optional[str] = None,
            platform_user=None) -> None:
    """The explicit go-ahead: the school's name typed exactly, and the
    admin's password (school side; the console's own login covers it)."""
    from ..models import School
    if r.status != "previewed":
        raise RestoreError("الطلب ده مش جاهز للتأكيد.")
    if mode not in ("replace", "add_missing"):
        raise RestoreError("اختار وضع الاسترجاع.")
    if not modules:
        raise RestoreError("اختار وحدة واحدة على الأقل.")
    school = db.session.get(School, r.school_id)
    if (typed_name or "").strip() != (school.name or "").strip():
        raise RestoreError("اسم المدرسة المكتوب مش مطابق.")
    if user is not None:
        _check_password(r, user, password)
    chosen, added = with_dependencies(modules)
    path = package_path(r)
    if path is None:
        raise RestoreError("ملف الحزمة غير موجود.")
    pkg = open_verified(path, r.school_id)
    try:
        plan = preview(pkg, r.school_id, chosen, mode, getattr(user, "id", r.requested_by_user_id))
    finally:
        pkg.close()
    if plan["blockers"]:
        raise RestoreError("مش ممكن الاسترجاع: " + "؛ ".join(plan["blockers"][:3]))
    r.modules, r.mode, r.status = chosen, mode, "confirmed"
    if user is not None:
        r.requested_by_user_id = user.id
    if platform_user is not None:
        r.platform_user_id = platform_user.id
    _audit("restore_confirm", r, user, added=added, platform_user_id=getattr(platform_user, "id", None))
    db.session.commit()


def run_confirmed(r) -> None:
    """Server CLI: the restore itself."""
    from .notifications import send_notification
    from .tenancy import tenant_context
    r.status, r.started_at = "running", datetime.now(timezone.utc)
    db.session.commit()
    path = package_path(r)
    try:
        if path is None:
            raise RestoreError("ملف الحزمة غير موجود.")
        out = run_restore(r.school_id, path, r.modules or [], r.mode, actor_user_id=r.requested_by_user_id)
        r.result, r.status = out, "succeeded"
        r.restore_point_backup_id = out.get("restore_point_backup_id")
    except Exception as e:                       # noqa: BLE001 — everything was rolled back
        db.session.rollback()
        r.status = "failed"
        r.error = (str(e) if isinstance(e, (RestoreError, engine.BackupError)) else type(e).__name__)[:255]
    r.finished_at = datetime.now(timezone.utc)
    _audit("restore_ok" if r.status == "succeeded" else "restore_failed", r, None,
           result=r.result, error=r.error)
    db.session.commit()
    with tenant_context(r.school_id):
        send_notification(r.school_id, "school_restore",
                          {"title": "استرجاع النسخة الاحتياطية", "status": r.status,
                           "message": "تم الاسترجاع بنجاح." if r.status == "succeeded"
                           else "فشل الاسترجاع ومفيش أي بيانات اتغيرت."},
                          related_kind="school_restore", related_id=r.id)


def request_undo(r, *, user=None, password: Optional[str] = None, platform_user=None, reason=None):
    """A new restore from r's restore point, same modules, replace mode —
    confirmed by the same password check."""
    from ..models import School, SchoolBackup, SchoolRestore
    if r.status != "succeeded" or not r.restore_point_backup_id:
        raise RestoreError("مفيش نقطة استرجاع للطلب ده.")
    point = db.session.get(SchoolBackup, r.restore_point_backup_id)
    if point is None or point.school_id != r.school_id or point.status != "succeeded":
        raise RestoreError("نقطة الاسترجاع مش موجودة.")
    _open_request_guard(r.school_id)
    undo = SchoolRestore(school_id=r.school_id, status="previewed", mode="replace",
                         source_backup_id=point.id, package_file=point.file_name, undo_of_id=r.id,
                         requested_by_user_id=getattr(user, "id", None),
                         platform_user_id=getattr(platform_user, "id", None), reason=reason)
    db.session.add(undo)
    db.session.flush()
    school = db.session.get(School, r.school_id)
    try:
        confirm(undo, modules=list(r.modules or []), mode="replace", typed_name=school.name, user=user,
                password=password, platform_user=platform_user)
    except RestoreError:
        db.session.rollback()
        raise
    return undo


def run_queue(limit: int = 3) -> int:
    from ..models import SchoolRestore
    n = 0
    for r in (SchoolRestore.query.filter_by(status="pending_preview")
              .order_by(SchoolRestore.id).limit(limit).all()):
        run_preview(r)
        n += 1
    for r in (SchoolRestore.query.filter_by(status="confirmed")
              .order_by(SchoolRestore.id).limit(limit).all()):
        run_confirmed(r)
        n += 1
    return n

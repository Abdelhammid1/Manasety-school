"""SAAS-050 — flask system-restore: the dump is validated before anything
changes, dry-run writes nothing, the restore goes into a NEW database and
is checked (row counts, integrity), config differences never show values.

The end-to-end drill needs PostgreSQL + pg_dump / psql (CI has both); on
SQLite the same test asserts the command refuses ("needs PostgreSQL")."""

from __future__ import annotations

import gzip
import io
import os
import shutil
import subprocess
import tarfile

import pytest
import sqlalchemy as sa


def _dump_text(app, tables, *, complete=True, cut_in_copy=False) -> str:
    lines = ["-- PostgreSQL database dump", ""]
    for t in tables:
        lines += [f"CREATE TABLE public.{t} (", "    id integer", ");", ""]
    lines += ["COPY public.subjects (id, name) FROM stdin;", "1\tMath", "2\tScience"]
    if cut_in_copy:
        return "\n".join(lines) + "\n"
    lines += ["\\.", ""]
    if complete:
        lines += ["", "-- PostgreSQL database dump complete", ""]
    return "\n".join(lines) + "\n"


def _write_gz(path, text):
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _all_tables(app):
    from app.services import system_restore as sr
    with app.app_context():
        return sorted(sr.expected_tables())


def test_dump_inspection_reads_tables_rows_and_marker(app, tmp_path):
    from app.services import system_restore as sr
    p = _write_gz(tmp_path / "ok.sql.gz", _dump_text(app, ["subjects", "grades"]))
    info = sr.inspect_dump(p)
    assert info.complete and info.tables == {"subjects", "grades"} and info.rows == {"subjects": 2}
    assert not sr.inspect_dump(_write_gz(tmp_path / "cut.sql.gz",
                                         _dump_text(app, ["subjects"], complete=False))).complete
    assert not sr.inspect_dump(_write_gz(tmp_path / "cut2.sql.gz",
                                         _dump_text(app, ["subjects"], cut_in_copy=True))).complete
    bad = tmp_path / "bad.sql.gz"
    bad.write_bytes(b"not gzip at all")
    with pytest.raises(sr.SystemRestoreError):
        sr.inspect_dump(bad)


@pytest.mark.parametrize("case", ["incomplete", "missing_table", "live_target", "bad_name"])
def test_refused_before_any_change(app, tmp_path, case, monkeypatch):
    from app.services import system_restore as sr
    tables = _all_tables(app)
    if case == "missing_table":
        tables = [t for t in tables if t != "students"]
    p = _write_gz(tmp_path / "d.sql.gz", _dump_text(app, tables, complete=case != "incomplete"))
    calls = []
    monkeypatch.setattr(sr, "_create_database", lambda name: calls.append(name))
    monkeypatch.setattr(sr, "_load_dump", lambda *a: calls.append("load"))
    target = {"live_target": None, "bad_name": "Bad-Name;drop"}.get(case, "restore_drill_x")
    with app.app_context():
        if target is None:
            target = sa.engine.make_url(str(__import__("app.extensions", fromlist=["db"]).db.engine.url)).database
            target = (target or "x").lower()
        with pytest.raises(sr.SystemRestoreError):
            sr.run(db_dump=p, target_db=target, apply=True)
    assert calls == []


def test_dry_run_writes_nothing(app, tmp_path, monkeypatch):
    from app.services import system_restore as sr
    p = _write_gz(tmp_path / "d.sql.gz", _dump_text(app, _all_tables(app)))
    calls = []
    monkeypatch.setattr(sr, "_create_database", lambda name: calls.append(name))
    monkeypatch.setattr(sr, "_load_dump", lambda *a: calls.append("load"))
    with app.app_context():
        rep = sr.run(db_dump=p, target_db="restore_drill_dry", apply=False)
    assert rep.ok and rep.dry_run and calls == []


def test_config_diff_shows_env_key_names_never_values(app, tmp_path):
    from app.services import system_restore as sr
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / ".env").write_text("SECRET_KEY=current-very-secret\nKEEP=1\nOLD_ONLY=x\n", encoding="utf-8")
    arch = tmp_path / "config.tar.gz"
    with tarfile.open(arch, "w:gz") as t:
        for name, body in ((".env", "SECRET_KEY=restored-other-secret\nKEEP=1\nNEW_ONLY=y\n"),
                           ("nginx/schools.conf", "server { listen 443; }\n")):
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    lines = sr.config_diff(arch, app_dir)
    text = "\n".join(lines)
    assert ".env + NEW_ONLY" in text and ".env - OLD_ONLY" in text and "SECRET_KEY" in text
    assert "current-very-secret" not in text and "restored-other-secret" not in text
    assert "KEEP" not in text                         # unchanged keys aren't listed
    backup = sr.apply_env(arch, app_dir)
    assert backup and backup.read_text(encoding="utf-8").startswith("SECRET_KEY=current")
    assert (app_dir / ".env").read_text(encoding="utf-8").startswith("SECRET_KEY=restored")


def test_uploads_archive_with_unsafe_paths_is_refused(app, tmp_path, monkeypatch):
    from app.services import system_restore as sr
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    arch = tmp_path / "u.tar.gz"
    with tarfile.open(arch, "w:gz") as t:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    with app.app_context():
        with pytest.raises(sr.SystemRestoreError):
            sr._restore_files(arch, sr.Report(dry_run=False), apply=True)
    assert not (tmp_path / "escape.txt").exists()


def _pg_tool(name):
    return shutil.which(name) or (os.path.join(os.environ["PG_BIN"], name) if os.environ.get("PG_BIN") else None)


def test_full_drill_restores_into_a_new_database(app, world, tmp_path):
    """pg_dump of the test database → system-restore --apply → a new
    database with the same row counts and a clean tenant integrity."""
    from app.extensions import db
    from app.services import system_restore as sr
    with app.app_context():
        url = sa.engine.make_url(str(db.engine.url))
    if url.get_backend_name() != "postgresql":
        p = _write_gz(tmp_path / "d.sql.gz", _dump_text(app, _all_tables(app)))
        with app.app_context(), pytest.raises(sr.SystemRestoreError, match="PostgreSQL"):
            sr.run(db_dump=p, target_db="restore_drill_sqlite", apply=True)
        return
    pg_dump, psql = _pg_tool("pg_dump"), _pg_tool("psql")
    assert pg_dump and psql, "PostgreSQL client tools (pg_dump, psql) are needed for the drill"
    dump = tmp_path / "drill.sql.gz"
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    out = subprocess.run([pg_dump, "-h", url.host or "localhost", "-p", str(url.port or 5432),
                          "-U", url.username or "", "--no-owner", "--no-privileges", url.database],
                         capture_output=True, env=env, check=True)
    with gzip.open(dump, "wb") as fh:
        fh.write(out.stdout)
    target = f"restore_drill_{os.getpid()}"
    try:
        with app.app_context():
            rep = sr.run(db_dump=dump, target_db=target, apply=True, psql=psql)
        assert rep.ok, rep.as_dict()
        names = [s.name for s in rep.steps]
        assert "row counts match the dump" in names and "tenant-integrity-check" in names
        assert rep.rows.get("students", 0) >= 2 and rep.rows.get("schools", 0) >= 2
    finally:
        eng = sa.create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)'))
        eng.dispose()

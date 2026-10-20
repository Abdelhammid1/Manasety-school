"""SAAS-038 — guard: nothing from the separate single-tenant system comes back.

Fails when a tracked file contains that system's host name, or when a
tracked file is byte-identical to one of the removed brand assets
(tests/forbidden_asset_hashes.txt holds only sha256 values, no names).
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Built from parts so this file itself never matches the scan.
FORBIDDEN_HOST = "school" + "." + "manasety" + ".ai"
GUARD_FILES = {"tests/test_no_foreign_branding.py", "tests/forbidden_asset_hashes.txt"}


def _tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def _forbidden_hashes():
    lines = (ROOT / "tests" / "forbidden_asset_hashes.txt").read_text(encoding="utf-8").splitlines()
    return {l.strip() for l in lines if l.strip() and not l.startswith("#")}


def test_no_tracked_file_mentions_the_other_system():
    hits = []
    for rel in _tracked():
        if rel in GUARD_FILES:
            continue
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        if FORBIDDEN_HOST.encode() in path.read_bytes().lower():
            hits.append(rel)
    assert hits == [], f"{FORBIDDEN_HOST} found in: {hits}"


def test_no_tracked_file_is_a_removed_brand_asset():
    bad = _forbidden_hashes()
    assert len(bad) >= 10
    hits = [rel for rel in _tracked()
            if (ROOT / rel).is_file()
            and hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() in bad]
    assert hits == [], f"removed brand asset is back: {hits}"


def test_mobile_folder_is_not_tracked():
    assert not [p for p in _tracked() if p.startswith("mobile/")]


def test_guard_catches_the_host_name(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text(f"see https://{FORBIDDEN_HOST}/api", encoding="utf-8")
    assert FORBIDDEN_HOST.encode() in f.read_bytes().lower()


def test_public_pages_carry_manasety_meta(app, two_schools):
    with app.test_client() as c:
        html = c.get("/auth/login", base_url="http://alpha.manasety.ai").get_data(as_text=True)
    assert 'property="og:site_name" content="منصتي"' in html
    assert "http://alpha.manasety.ai/static/img/og-default.png" in html
    assert 'rel="canonical" href="http://alpha.manasety.ai/auth/login"' in html
    assert "img/favicon.png" in html and "img/apple-touch-icon.png" in html
    assert FORBIDDEN_HOST not in html

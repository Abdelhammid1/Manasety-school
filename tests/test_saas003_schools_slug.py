"""SAAS-003 — schools.slug + schools.status validator + reserved list.

Unit coverage of the validate_slug / RESERVED_SLUGS / SCHOOL_STATUSES
contract that both the model layer and (next ticket) the host
resolver read from. The migration itself is exercised by hand via
`flask db upgrade` and the "running head" check below.
"""

from __future__ import annotations

import pytest

from app.services.tenancy import (
    RESERVED_SLUGS, SCHOOL_STATUSES,
    SlugValidationError, normalize_slug, validate_slug,
)


# ─── normalize_slug ───────────────────────────────────────────────────

def test_normalize_lowercases_and_strips():
    assert normalize_slug("  Demo  ") == "demo"
    assert normalize_slug("MY-SCHOOL") == "my-school"
    assert normalize_slug(None) == ""
    assert normalize_slug("") == ""


# ─── valid cases ──────────────────────────────────────────────────────

@pytest.mark.parametrize("slug", [
    "a", "abc", "my-school", "k12",
    "a1-b2-c3",
    "a" + "b" * 61 + "c",   # 63 chars, max length
])
def test_valid_slugs_pass(slug):
    assert validate_slug(slug) == slug.lower()


# ─── invalid formats ──────────────────────────────────────────────────

@pytest.mark.parametrize("bad,reason_fragment", [
    ("",            "مطلوب"),
    ("   ",         "مطلوب"),
    ("a" * 64,      "طويل"),
    ("-abc",        "ولا ينتهي"),
    ("abc-",        "ولا ينتهي"),
    ("ab_cd",       "الشرطة"),
    ("ab.cd",       "الشرطة"),
    ("ab cd",       "الشرطة"),
    ("مدرسة",       "الشرطة"),  # Arabic script — not allowed
])
def test_invalid_formats_rejected(bad, reason_fragment):
    with pytest.raises(SlugValidationError) as e:
        validate_slug(bad)
    assert reason_fragment in str(e.value)


# ─── reserved list ────────────────────────────────────────────────────

@pytest.mark.parametrize("reserved", [
    "lms", "demo", "admin", "www", "api",
    "auth", "login", "pay", "billing",
])
def test_reserved_slugs_rejected(reserved):
    with pytest.raises(SlugValidationError) as e:
        validate_slug(reserved)
    assert "محجوز" in str(e.value)
    assert reserved in RESERVED_SLUGS


def test_reserved_check_is_case_insensitive():
    with pytest.raises(SlugValidationError):
        validate_slug("LMS")
    with pytest.raises(SlugValidationError):
        validate_slug("DeMo")


# ─── status enum ──────────────────────────────────────────────────────

def test_school_statuses_covers_the_three_values():
    assert SCHOOL_STATUSES == ("active", "suspended", "archived")

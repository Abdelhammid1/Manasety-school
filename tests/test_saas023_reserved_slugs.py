"""SAAS-023 — slugs taken by live subdomains / sister products."""

import pytest

from app.services.tenancy import (
    RESERVED_SLUGS, SlugValidationError, validate_slug, validate_slug_format,
)

NGINX_LIVE = ["accountant", "chatwoot", "drporcelain", "easygo", "eg-uae", "lamma",
              "lexoffice", "marsoud", "n8n", "qafer", "whitemoon", "www"]
LAMMA = ["almustashar", "activefit", "elyasmin", "qaffer", "qafer", "sobou", "invitation",
         "landing", "blog", "support", "help", "status", "mail", "ftp", "api", "cdn",
         "static", "media", "test", "preview", "about", "contact", "terms", "privacy",
         "pricing", "faq", "lms", "admin", "app", "school", "wedding", "birthday", "create"]


@pytest.mark.parametrize("slug", sorted(set(NGINX_LIVE + LAMMA)))
def test_reserved_names_are_refused(slug):
    assert slug in RESERVED_SLUGS
    with pytest.raises(SlugValidationError):
        validate_slug(slug)
    with pytest.raises(SlugValidationError):
        validate_slug(slug.upper())


@pytest.mark.parametrize("slug", ["n8n2", "lamma-school", "marsoud-academy", "alnoor", "qafer1"])
def test_near_names_are_accepted(slug):
    assert validate_slug(slug) == slug


def test_demo_stays_usable_for_the_existing_tenant():
    with pytest.raises(SlugValidationError):
        validate_slug("demo")                 # no NEW school may take it
    assert validate_slug_format("demo") == "demo"   # resolver still accepts it


def test_reserved_list_is_defined_once():
    import pathlib
    hits = [p for p in pathlib.Path("app").rglob("*.py")
            if '"chatwoot"' in p.read_text(encoding="utf-8")]
    assert [p.as_posix() for p in hits] == ["app/services/tenancy.py"]

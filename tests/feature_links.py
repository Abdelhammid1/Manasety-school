"""Static check for ticket C: a link from one module's templates into a
page that can be turned off must sit inside a guard for that page —
`{% if endpoint_on('<endpoint>') %}` or `feature_on('<its feature>')`
(module_on alone is not enough: a page can be off while its module is on).

A link inside its own module's templates is not checked (a page of a
module links to that module's other pages; the crawler covers the main
pages). A deliberate exception carries `{# feature-link-ok: <why> #}` on
the same line.
"""

from __future__ import annotations

import pathlib
import re

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"
# Template folders → the module whose pages they render.
FOLDER_MODULE = {
    "academic": "academic", "teachers": "academic", "students": "students", "attendance": "attendance",
    "schedule": "schedule", "results": "results", "lms": "lms", "courses": "lms", "nafis": "nafis",
    "finance": "finance", "hr": "hr", "portal": "portal", "admin": "core", "messaging": "core",
    "auth": "core",
}
# platform/ holds pages of several modules: by file name.
PLATFORM_FILES = {"rooms_list": "schedule", "room_detail": "schedule", "room_form": "schedule",
                  "substitutions": "schedule", "imports": "students", "imports_preview": "students",
                  "staff_attendance": "hr", "audit_log_viewer": "core", "user_scopes": "core"}
# partials/ and dashboard/ show on every page of every module: always checked.
SKIP_FOLDERS = {"superadmin"}                     # the console: no school features
TAG_RE = re.compile(r"{%-?\s*(if|elif|else|endif|for|endfor|macro|endmacro|call|endcall)\b(.*?)-?%}", re.S)
URL_RE = re.compile(r"url_for\(\s*['\"]([\w.]+)['\"]")
OK_MARK = "feature-link-ok"


def _guards(text: str, pos: int) -> list[str]:
    """The conditions of the {% if %} blocks open at `pos` (else branches
    don't inherit the condition)."""
    stack: list[str] = []
    for m in TAG_RE.finditer(text, 0, pos):
        kind, rest = m.group(1), m.group(2)
        if kind in ("if", "for", "macro", "call"):
            stack.append(rest if kind in ("if", "for") else "")   # a for's `if` filter guards too
        elif kind in ("elif", "else"):
            if stack:
                stack[-1] = rest if kind == "elif" else ""
        elif stack:
            stack.pop()
    return stack


def unguarded_links():
    """[(template, line, endpoint)] for every link that needs a guard."""
    from app.services.modules import (ESSENTIAL_FEATURES, feature_for_endpoint, module_for_endpoint)
    out = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        rel = path.relative_to(TEMPLATES).as_posix()
        folder = rel.split("/", 1)[0] if "/" in rel else ""
        if folder in SKIP_FOLDERS:
            continue
        own_module = (PLATFORM_FILES.get(path.stem) if folder == "platform" else FOLDER_MODULE.get(folder))
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for m in URL_RE.finditer(text):
            ep = m.group(1)
            feature = feature_for_endpoint(ep)
            if feature is None or feature in ESSENTIAL_FEATURES:
                continue
            if module_for_endpoint(ep, "") == own_module:
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            if OK_MARK in lines[line_no - 1]:
                continue
            # the guards open here, plus an inline `… if endpoint_on(…) else …` on the line
            conds = " ".join(_guards(text, m.start())) + " " + lines[line_no - 1]
            if f"endpoint_on('{ep}')" in conds or f'endpoint_on("{ep}")' in conds \
                    or f"feature_on('{feature}')" in conds or f'feature_on("{feature}")' in conds:
                continue
            out.append((rel, line_no, ep))
    return out

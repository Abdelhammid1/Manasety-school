"""Codes for record ids in web links: /students/xK9aBc2Q, not /students/46.

The internal id is global across schools, so a raw number shows how big
the system is and in what order rows were made, and invites guessing.
The code hides only that: school_id filtering in every query stays the
protection (a code of school B's row on school A is still a 403 / 404).

  * `<hid:student_id>` in a route: the view gets the int back; a code
    that doesn't decode (garbage, a raw number, empty) doesn't match → 404.
  * url_for(..., student_id=46) builds the code — inside or outside a
    request (emails, jobs), as long as there is an app context.
  * `{{ x.id|hid }}` in a template / `encode(n)` in Python for the few
    URLs built by hand or in JavaScript.

One salt for the whole platform (HASHIDS_SALT, config.py), no school or
request in it: converters run before before_request and in url_for
outside a request. Pure arithmetic, no queries.
"""

from __future__ import annotations

from typing import Optional

from flask import current_app, has_app_context
from hashids import Hashids
from werkzeug.routing import BaseConverter, ValidationError

MIN_LENGTH = 8
_EXT = "hashids"
_last: Optional[Hashids] = None        # the most recent app's, for code without an app context


def init_app(app) -> None:
    global _last
    hasher = Hashids(salt=app.config["HASHIDS_SALT"], min_length=MIN_LENGTH)
    app.extensions[_EXT] = hasher
    _last = hasher
    # before any blueprint registers: rules are parsed at registration
    app.url_map.converters["hid"] = HashidConverter
    app.jinja_env.filters["hid"] = encode


def _hasher() -> Hashids:
    if has_app_context() and _EXT in current_app.extensions:
        return current_app.extensions[_EXT]
    if _last is None:
        raise RuntimeError("hashid.init_app(app) has not run")
    return _last


def encode(value) -> str:
    """Record id (int, or a string of digits) → its link code."""
    if isinstance(value, bool):
        raise ValueError("not a record id")
    n = int(value)
    if n < 0:
        raise ValueError("not a record id")
    return _hasher().encode(n)


def decode(code) -> Optional[int]:
    """Link code → record id; None for anything that isn't one of ours
    (Hashids re-encodes and compares, so a tampered code fails too)."""
    if not isinstance(code, str) or len(code) < MIN_LENGTH:
        return None
    vals = _hasher().decode(code)
    return vals[0] if len(vals) == 1 else None


class HashidConverter(BaseConverter):
    regex = r"[A-Za-z0-9]{%d,}" % MIN_LENGTH

    def to_python(self, value: str) -> int:
        n = decode(value)
        if n is None:
            raise ValidationError()             # no match → 404, never a 500
        return n

    def to_url(self, value) -> str:
        return encode(value)

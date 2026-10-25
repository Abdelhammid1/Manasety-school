"""A school's own look inside the platform: its logo, its name and its
primary colour on every page its users see (school hosts only — the
console keeps the Manasety identity).

  * colour — `School.primary_color` (#RRGGBB or NULL). `theme_css()`
    derives the brand token family (primary, secondary, navy and their
    tints) as `R G B` triplets for the Tailwind tokens in stitch_base,
    which read `rgb(var(--c-x, <current default>) / <alpha-value>)`: a
    school without a colour renders exactly as before, pixel for pixel.
    A colour too light for white text (contrast under 4.5:1) is darkened
    to the nearest readable shade. Semantic colours (success / warning /
    error), tertiary and the neutral surfaces never change.
  * logo — served without login by /branding/logo for the host's school
    only (blueprints/branding.py); `logo_src()` is its versioned URL.

Every value is validated with HEX_RE before it reaches a page (no CSS
injection), at save time and again at render time.
"""

from __future__ import annotations

import colorsys
import re
from typing import Optional

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MIN_CONTRAST = 4.5


def normalize_hex(value) -> Optional[str]:
    """`#RRGGBB` (upper case) or None for anything else."""
    v = (value or "").strip()
    return v.upper() if HEX_RE.match(v) else None


# ─── colour maths ───────────────────────────────────────────────────

def _rgb(hex_: str) -> tuple[int, int, int]:
    return int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_with_white(hex_: str) -> float:
    return 1.05 / (_luminance(_rgb(hex_)) + 0.05)


def _hls(hex_: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in _rgb(hex_))
    return colorsys.rgb_to_hls(r, g, b)


def _from_hls(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return _hex((r * 255, g * 255, b * 255))


def readable(hex_: str) -> str:
    """The colour, darkened just enough for white text on it (>= 4.5:1)."""
    h, l, s = _hls(hex_)
    out = hex_.upper()
    while contrast_with_white(out) < MIN_CONTRAST and l > 0:
        l -= 0.01
        out = _from_hls(h, l, s)
    return out


def _tone(h, s, l, *, min_contrast: float = 0.0) -> str:
    out = _from_hls(h, l, s)
    while min_contrast and contrast_with_white(out) < min_contrast and l > 0:
        l -= 0.01
        out = _from_hls(h, l, s)
    return out


def palette(chosen: str) -> dict[str, str]:
    """The brand token family for `chosen` (hex each). `primary-container`
    is the (readable) chosen colour itself: the gradient start and the
    main buttons; `primary` a deeper shade used as text."""
    base = readable(chosen)
    h, l, s = _hls(base)
    grey = s < 0.12                       # a grey stays grey (its hue means nothing)
    s = s if grey else max(s, 0.35)
    sec_h = h
    return {
        "primary-container":        base,
        "primary":                  _tone(h, s, min(l, 0.30) - 0.08, min_contrast=7),
        "primary-fixed":            _tone(h, s, 0.93),
        "primary-fixed-dim":        _tone(h, s, 0.85),
        "on-primary-container":     _tone(h, s, 0.78),
        "on-primary-fixed":         _tone(h, s, 0.10),
        "on-primary-fixed-variant": _tone(h, s, 0.36, min_contrast=MIN_CONTRAST),
        "secondary":                _tone(sec_h, s if grey else min(1.0, s + 0.2), 0.42, min_contrast=MIN_CONTRAST),
        "secondary-container":      _tone(sec_h, s, 0.97),
        "secondary-fixed":          _tone(sec_h, s, 0.93),
        "secondary-fixed-dim":      _tone(sec_h, s, 0.84),
        "on-secondary-fixed":       _tone(sec_h, s, 0.12),
        "on-secondary-fixed-variant": _tone(sec_h, s, 0.33, min_contrast=MIN_CONTRAST),
        "surface-tint":             _tone(h, s * 0.6, 0.46),
        "inverse-primary":          _tone(h, s, 0.85),
        "navy":                     _tone(h, min(s, 0.75), 0.21, min_contrast=10),
        "sidebar-icon":             _tone(h, min(s, 0.6), 0.93),
        "gradient-mid":             _tone(sec_h, s if grey else min(1.0, s + 0.15), 0.50, min_contrast=MIN_CONTRAST),
        "gradient-end":             _tone(h + (0 if grey else 0.06), s if grey else min(1.0, s + 0.1), 0.42,
                                          min_contrast=MIN_CONTRAST),
    }


def _triplet(hex_: str) -> str:
    r, g, b = _rgb(hex_)
    return f"{r} {g} {b}"


def theme_css(chosen) -> str:
    """`:root{--c-primary: R G B; …}` for a valid colour, "" otherwise
    (the stylesheet's fallbacks are the platform's own colours)."""
    hex_ = normalize_hex(chosen)
    if hex_ is None:
        return ""
    p = palette(hex_)
    vars_ = [f"--c-{k}:{_triplet(v)}" for k, v in p.items()]
    vars_.append(f"--c-navy-surface:{_triplet(p['navy'])}")
    vars_.append("--brand-gradient:linear-gradient(135deg,{0} 0%,{1} 55%,{2} 100%)".format(
        p["primary-container"], p["gradient-mid"], p["gradient-end"]))
    vars_.append("--brand-gradient-deep:linear-gradient(135deg,{0} 0%,{1} 45%,{2} 100%)".format(
        p["navy"], p["primary-container"], p["gradient-mid"]))
    vars_.append(f"--brand-hex:{p['primary-container']}")
    return ":root{" + ";".join(vars_) + "}"


def was_darkened(chosen) -> bool:
    hex_ = normalize_hex(chosen)
    return bool(hex_) and readable(hex_) != hex_


# ─── the logo ───────────────────────────────────────────────────────

def has_own_logo(school) -> bool:
    """A logo this school stored with us (an old external URL counts as none)."""
    url = getattr(school, "logo_url", None) or ""
    sid = getattr(school, "id", None)
    return bool(sid) and url.startswith(f"/files/{int(sid)}/logo/")


def logo_version(school) -> str:
    """Changes with every new upload (each upload gets a new file name)."""
    import hashlib
    return hashlib.sha256((getattr(school, "logo_url", None) or "").encode()).hexdigest()[:10]


# ─── per request ────────────────────────────────────────────────────

def current_school():
    """The school whose pages these are: the host's (tenant resolution),
    else the signed-in user's. None on the console / platform host. No
    query when the host already resolved it."""
    from flask import g, has_request_context
    if not has_request_context():
        return None
    resolved = getattr(g, "tenant_resolved", None)
    if resolved is not None:
        return resolved.school if resolved.kind == "tenant" else None
    from flask_login import current_user
    if getattr(current_user, "is_authenticated", False) and not getattr(current_user, "is_platform_user", False):
        from ..extensions import db
        from ..models import School
        return db.session.get(School, current_user.school_id)
    return None


def context() -> dict:
    """What the templates use (`brand`), once per request."""
    from flask import g, has_request_context, url_for
    if not has_request_context():                 # an email or a job: the platform's own
        return {"school": None, "name": "", "own_logo": False, "theme_css": "", "branded": False,
                "site_name": "منصتي", "logo_src": "/static/img/logo.svg"}
    if "brand" in g:
        return g.brand
    school = current_school()
    own = school is not None and has_own_logo(school)
    brand = {
        "school": school,
        "name": school.name if school is not None else "",
        "own_logo": own,
        "logo_src": (url_for("branding.logo", v=logo_version(school)) if own
                     else url_for("static", filename="img/logo.svg")),
        "theme_css": theme_css(getattr(school, "primary_color", None)) if school is not None else "",
    }
    # its own identity (a logo or a colour): the title / meta / icons say so
    brand["branded"] = bool(own or brand["theme_css"])
    brand["site_name"] = brand["name"] if brand["branded"] else "منصتي"
    g.brand = brand
    return brand

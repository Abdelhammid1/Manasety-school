"""Module keys a plan may enable. SAAS-030 fills this in with the full
catalogue (blueprints, sidebar groups, permissions); for now it only
validates plan.modules. "*" means every module (the internal plan)."""
from __future__ import annotations

# Placeholder catalogue — replaced by the discovered list in SAAS-030.
MODULE_KEYS: tuple[str, ...] = (
    "students", "attendance", "academic", "results", "schedule", "lms",
    "finance", "hr", "portal", "nafis", "messaging",
)


def validate_plan_modules(keys) -> list[str]:
    keys = [k.strip().lower() for k in keys if k and k.strip()]
    if "*" in keys:
        return ["*"]
    unknown = sorted(set(keys) - set(MODULE_KEYS))
    if unknown:
        raise ValueError(f"موديولات غير معروفة: {', '.join(unknown)}")
    return sorted(set(keys))

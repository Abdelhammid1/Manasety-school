"""SAAS-036 — who may do what on the console. ONE matrix.

CAPABILITIES: capability → roles allowed. ROUTES: every console endpoint
→ {method: capability}. The console gate refuses (403) any endpoint /
method that isn't in ROUTES (fail closed), and tests/test_saas036_*
checks every role against every route, so a new route without an entry
fails the suite.
"""
from __future__ import annotations

OWNER, SUPPORT, FINANCE = "owner", "support", "finance"
ALL = frozenset({OWNER, SUPPORT, FINANCE})

CAPABILITIES: dict[str, frozenset[str]] = {
    "public": ALL,                                   # login flow (gated separately)
    "self": ALL,                                     # own password / sessions / logout
    "schools.read": ALL,                             # list + details (counts only)
    "schools.create": frozenset({OWNER}),            # 028
    "schools.edit": frozenset({OWNER}),              # 032
    "plans.read": ALL,                               # support reads
    "plans.write": frozenset({OWNER, FINANCE}),      # 026
    "modules.write": frozenset({OWNER}),             # 030
    "limits.write": frozenset({OWNER, FINANCE}),     # 030 (finance: limits only)
    "support.read_only": frozenset({OWNER, SUPPORT}),   # 031
    "support.sessions": frozenset({OWNER}),          # list / revoke
    "staff.tools": frozenset({OWNER, SUPPORT}),      # 032 (credential actions: owner, in the view)
    "schools.dangerous": frozenset({OWNER}),         # 032 suspend / archive / slug
    "schools.notes": ALL,
    "schools.contacts": frozenset({OWNER, FINANCE}),
    "announcements": frozenset({OWNER}),
    "nginx.sync": frozenset({OWNER, SUPPORT}),
    "billing": frozenset({OWNER, FINANCE}),          # 033 — support sees nothing financial
    "monitoring.read": ALL,                          # 034 (finance: read)
    "monitoring.ack": frozenset({OWNER, SUPPORT}),
    "offboarding": frozenset({OWNER}),               # 035
    "platform_users": frozenset({OWNER}),            # 036
    "audit": frozenset({OWNER}),
}

G, P = "GET", "POST"
ROUTES: dict[str, dict[str, str]] = {
    "superadmin.login": {G: "public", P: "public"},
    "superadmin.totp": {G: "public", P: "public"},
    "superadmin.totp_setup": {G: "public", P: "public"},
    "superadmin.setup": {G: "public", P: "public"},
    "superadmin.logout": {P: "self"},
    "superadmin.password": {G: "self", P: "self"},
    "superadmin.my_sessions": {G: "self"},
    "superadmin.my_session_revoke": {P: "self"},
    "superadmin.home": {G: "schools.read"},
    "superadmin.schools": {G: "schools.read"},
    "superadmin.school_detail": {G: "schools.read"},
    "superadmin.plans": {G: "plans.read"},
    "superadmin.plan_new": {P: "plans.write"},
    "superadmin.plan_edit": {P: "plans.write"},
    "superadmin.plan_toggle": {P: "plans.write"},
    "superadmin.subscription_renew": {P: "plans.write"},
    "superadmin.subscription_extend": {P: "plans.write"},
    "superadmin.subscription_change_plan": {P: "plans.write"},
    "superadmin.subscription_trial": {P: "plans.write"},
    "superadmin.school_new": {G: "schools.create"},
    "superadmin.school_new_step": {P: "schools.create"},
    "superadmin.school_create": {P: "schools.create"},
    "superadmin.slug_check": {G: "schools.create"},
    "superadmin.school_nginx_sync": {P: "nginx.sync"},
    "superadmin.school_module_set": {P: "modules.write"},
    "superadmin.school_limits_set": {P: "limits.write"},
    "superadmin.support_start": {P: "support.read_only"},
    "superadmin.support_sessions": {G: "support.sessions"},
    "superadmin.support_session_detail": {G: "support.sessions"},
    "superadmin.support_revoke": {P: "support.sessions"},
    "superadmin.school_edit": {G: "schools.edit", P: "schools.edit"},
    "superadmin.school_lifecycle": {P: "schools.dangerous"},
    "superadmin.school_slug_change": {P: "schools.dangerous"},
    "superadmin.school_staff": {G: "staff.tools"},
    "superadmin.school_staff_action": {P: "staff.tools"},
    "superadmin.school_note_add": {P: "schools.notes"},
    "superadmin.school_contact_add": {P: "schools.contacts"},
    "superadmin.school_contact_delete": {P: "schools.contacts"},
    "superadmin.school_tags_set": {P: "schools.notes"},
    "superadmin.announcements": {G: "announcements", P: "announcements"},
    "superadmin.announcement_delete": {P: "announcements"},
    "superadmin.offboarding": {G: "offboarding"},
    "superadmin.offboarding_step": {P: "offboarding"},
    "superadmin.export_download": {P: "offboarding"},
    "superadmin.dashboard": {G: "monitoring.read"},
    "superadmin.system_health": {G: "monitoring.read"},
    "superadmin.alerts": {G: "monitoring.read"},
    "superadmin.alert_ack": {P: "monitoring.ack"},
    "superadmin.billing": {G: "billing"},
    "superadmin.invoice_new": {G: "billing", P: "billing"},
    "superadmin.invoice_detail": {G: "billing"},
    "superadmin.invoice_issue": {P: "billing"},
    "superadmin.invoice_void": {P: "billing"},
    "superadmin.invoice_payment": {P: "billing"},
    "superadmin.payment_reverse": {P: "billing"},
    "superadmin.invoice_pdf": {G: "billing"},
    "superadmin.school_statement": {G: "billing"},
    "superadmin.billing_report": {G: "billing"},
    "superadmin.company_settings": {G: "billing", P: "billing"},
    "superadmin.users": {G: "platform_users", P: "platform_users"},
    "superadmin.user_action": {P: "platform_users"},
    "superadmin.audit": {G: "audit"},
}


def allowed(endpoint: str | None, method: str, role: str | None) -> bool:
    method = "GET" if method == "HEAD" else method
    cap = ROUTES.get(endpoint or "", {}).get(method)
    return cap is not None and role in CAPABILITIES[cap]


def is_public(endpoint: str | None) -> bool:
    return all(c == "public" for c in ROUTES.get(endpoint or "", {"x": "no"}).values())

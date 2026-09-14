# Changelog — Manasety Mobile

Both `parent_app` and `teacher_app` are versioned together with the shared
UI package `manasety_ui`. All notable changes to any of the three land
here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses semantic versioning (MAJOR.MINOR.PATCH+build).

---

## [0.4.1+6] — 2026-08-23

**Parent-app scoping + self-service username rename (Sprint 11).**

### Added
- **Self-service username / display-name edit** — new "تعديل الحساب"
  screen behind the pencil icon in the parent-app profile screen.
  * Full-name update: no password required.
  * Username update: requires current password (defense-in-depth) +
    3–32 char latin/digit/`._-` pattern + uniqueness check within school.
  * Backed by new endpoints `POST /me/username` + `POST /me/full-name`.
- **`AuthController.refreshUser()`** — refreshes the cached user from
  `/me` so profile-screen values update immediately after an edit.

### Changed
- **`/parent/notifications` refactored** to filter by direct
  `NotificationLog.student_id` FK instead of the fragile
  `target_phone` string match. Eliminates the cross-family leak that
  happened when two parent accounts shared a phone number.
- **`/parent/children` hardened** with an explicit
  `parent_user_id IS NOT NULL` guard and a debug-log line so future
  regressions are trivially diagnosable.

### Fixed
- Notification-scoping fragility (Concern #3): notifications now use a
  proper student FK. Phone-based fallback stays only for the outbound
  SMS gateway.

### Migrations
- `a1b2c3d4e5f6_sprint_11_notification_student_fk`: adds
  `notification_logs.student_id` FK + index, backfills existing rows
  by matching `target_phone == students.parent_phone` within a school.

### Ops
- New `scripts/audit_parent_children.py` — lists every parent user with
  their linked students, and flags orphaned students (parent_user_id
  IS NULL). Meant for a one-off run when a parent reports seeing
  children that don't belong to them (Concern #2 verdict: filter is
  correct in code; extras are likely data-side mis-linkage).

---

## [0.4.0+5] — 2026-08-18

**Naming & presentation overhaul (TKT-10 / TKT-11 / TKT-12 / TKT-13).**

### Changed
- **Unified commercial naming** — every user-facing "منصتي" string swapped to
  `بوابة ولي الأمر` / `بوابة المعلم` across Android launcher label, task
  switcher, iOS `CFBundleDisplayName`, notification channel, profile version
  footer, and TalkBack logo label. iOS + Android now show the same name
  under the app icon.
- **Splash re-baked per app** — the small watermark now reads the portal
  name (previously identical `منصتي` across both apps); the institution
  wordmark below is unchanged.
- **Screen title / tone consistency pass** — teacher hub's three-way
  inconsistency (`الفصول` / `فصولي` / `فصولك`) unified as `فصولك`;
  `جدولك` replaces `الجدول الأسبوعي`; grade-picker AppBar trimmed to
  `رصد الدرجات`.

### Added
- **Marketing screenshot pack** — 12 branded 1080×1920 PNGs under
  `mobile/docs/screenshots/{parent,teacher}/` for direct Play Console
  upload. Raw screencaps preserved in `raw/` for future re-composition.
- **Play Console store-listing pack** — `mobile/docs/store-listing.md`
  gives whoever runs Play Console the exact copy to paste (app names,
  short + full descriptions per app, corrected Data-safety declaration,
  support-contact recommendations, pre-publish checklist).
- **School-admin dashboard overhaul** (`/dashboard`) — metrics + alerts
  + shortcuts, matching the mobile brand. New `admin_only` decorator
  gates it to `role.name == 'admin'`.

### Fixed
- iOS `CFBundleDisplayName` was `مدرسة الصالح الشريف` (grammatically wrong —
  extra `ال` before `صالح`); now `بوابة ولي الأمر` / `بوابة المعلم`.

---

## [0.3.0+4] — 2026-08-15

Release-polish sprint (Days 0-13). Both apps are now demo-ready.

### Added
- **Shared `manasety_ui` package** — extracted 20+ widgets, `ManasetyTokens`
  theme extension, `SubjectPalette`, and `arabize()` helper into a single
  path-linked Dart package so both apps consume identical visual DNA.
  *(Days 0-2)*
- **Dark theme** with `ThemeMode.system` in both apps; navy + gold brand
  accents preserved across the flip. *(Day 2)*
- **`AttendanceDonut`** — threshold-colored hero ring on the parent
  attendance tab (green ≥90%, gold 70-90%, red <70%). *(Day 5)*
- **`AttendanceMonthGrid`** — 7-column calendar with per-day status
  color coding + prev/next month navigation. *(Day 5)*
- **`SubjectProgressBar`** with threshold-banded fill on the results tab.
  *(Day 5)*
- **`SubjectPalette`** — deterministic hash → color + icon map so the
  same subject looks the same on every screen. *(Day 6)*
- **`WeeklyScheduleGrid`** with subject-colored slot rails + tinted time
  chips + today outline. *(Day 6)*
- **Invoice status ribbon** with progress bar + StatusChip. *(Day 6)*
- **`NotificationGroupList`** — bucketed feed (اليوم / أمس / هذا الأسبوع /
  month-year) with unread red dots and Arabic relative time. *(Day 7)*
- **`AppRefreshIndicator`** — themed spinner + floating "تم التحديث"
  snackbar on completion. *(Day 8)*
- **`ManasetyPageTransitionsBuilder`** — RTL-aware slide+fade transitions
  everywhere. *(Day 8)*
- **`EmptyIllustration`** — 8 branded illustrations replacing bare
  Material glyphs for empty states. *(Day 9)*
- **Hero avatar flights** between parent child-list and detail. *(Day 10)*
- **Animated `StatusChip`** — fade+scale on kind/label change. *(Day 10)*
- **`ArabesqueBackground`** — 8-pointed-star tessellation used on the
  login scaffold + splash halo. *(Day 11)*
- **Full accessibility layer** — `Semantics` labels on every custom
  tappable card, chip, pill, and day-cell; TalkBack now announces
  status, count, and role for previously silent widgets. *(Day 12)*
- **Global text-scale cap** at 130 % so fixed-height chips stop
  overflowing at Android's "Largest" font. *(Day 12)*
- **Gold-tinted focus overlay** on every themed button. *(Day 12)*
- **`AppColors.goldInk` / `successInk` / `dangerInk`** — text-safe
  siblings that clear AA 4.5:1 on tinted backgrounds. *(Days 12-13)*
- **`RefreshableEmpty`** — makes empty states scroll so
  pull-to-refresh works on them too. *(Day 13)*
- **Branded native splash** — white circular medallion with gold ring +
  faint arabesque halo + institution wordmark. *(Day 12+13)*
- **Adaptive app icon** — emblem baked into the Android safe zone;
  parent stays navy, teacher moves to goldInk for at-a-glance
  differentiation on a shared home screen. *(Day 13)*
- **Runtime version string** in profile screen via `package_info_plus`
  (was hard-coded and drifted). *(Day 13)*

### Changed
- Snackbar copy warmth pass — save/submit success messages now read as
  "تمّ ... بنجاح ✓"; generic failures re-worded to be actionable
  ("لم نتمكن من ... — تحقق من الاتصال وحاول مجددًا"). *(Day 11)*
- Password-visibility toggles gained tooltips. *(Day 12)*
- Attendance status pills grew to a ≥48 dp touch target. *(Day 12)*
- Three subject-palette hues (teal, amber-brown, steel) darkened so raw
  color reads ≥4.5:1 on white. *(Day 13)*
- `StatusChip` reworked — warn / danger use solid accent bg + white fg;
  success / neutral use tint bg + ink fg. All variants now clear WCAG
  AA. *(Day 13)*

### Fixed
- **Windows Unicode crash** in `seeds/seed.py`. *(Day 0)*
- **Login card invisible in dark mode** — explicit light-mode override
  on the auth card. *(Day 5)*
- **"Nothing appears" invisible-cards bug** — redesigned `children_screen`
  and `sections_screen` with plain layouts, removing the `IntrinsicHeight`
  + `AccentRailCard` chain that collapsed to zero-height. *(Day 4.5)*
- **Container(color + decoration) assertion** crashing take-attendance
  and grade-entry screens. *(Day 12 hot-fix)*
- **`grade_picker_screen` unhandled throw** when sections list is empty
  — now shows an EmptyState. *(Day 12 hot-fix)*
- **RTL bug** — "unsaved edits" dirty rail was on the leading edge
  (`Border(right:)`); moved to trailing edge (`BorderDirectional(end:)`).
  *(Day 13)*

### Deferred
- **In-app "ما الجديد" onboarding screen** — nice-to-have for
  version-bump discovery; ship the changelog first.
- **Baseline widget / golden tests** — planned for a post-demo
  hardening sprint.
- **iOS icon differentiation** — client is Android-only for now.

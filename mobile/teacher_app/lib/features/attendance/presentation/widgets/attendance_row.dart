import 'package:flutter/material.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../../../../shared/models/attendance.dart';
import '../../../../shared/models/student_brief.dart';

class AttendanceRow extends StatelessWidget {
  final int index;
  final StudentBrief student;
  final AttendanceMark mark;
  final ValueChanged<AttendanceStatus> onStatus;
  final VoidCallback onNotes;

  const AttendanceRow({
    super.key,
    required this.index,
    required this.student,
    required this.mark,
    required this.onStatus,
    required this.onNotes,
  });

  @override
  Widget build(BuildContext context) {
    return Dismissible(
      key: ValueKey('att-row-${student.enrollmentId}'),
      background: _swipeBg(AppColors.success, Alignment.centerRight, Icons.check),
      secondaryBackground:
          _swipeBg(AppColors.danger, Alignment.centerLeft, Icons.close),
      confirmDismiss: (dir) async {
        onStatus(dir == DismissDirection.startToEnd
            ? AttendanceStatus.present
            : AttendanceStatus.absent);
        return false; // don't actually dismiss the row
      },
      // Day 12 — Parallel-channel hint for the color-only "unsaved edits"
      // right-side rail. Without this the SR user has no way to know the row
      // has pending changes.
      child: Semantics(
        hint: mark.dirty ? 'يوجد تغييرات غير محفوظة' : null,
        child: Container(
        // Day 13 — border was `right:` (physical). In RTL that's the leading
        // edge (where the avatar lives) — the "unsaved" rail belongs on the
        // trailing edge. `BorderDirectional(end:)` flips correctly per locale.
        decoration: BoxDecoration(
          color: Colors.white,
          border: BorderDirectional(
            bottom: BorderSide(color: context.tokens.border),
            end: BorderSide(
              color: mark.dirty ? AppColors.gold : Colors.transparent,
              width: 4,
            ),
          ),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                // Day 12 — Index number is a visual counter only; sibling name
                // and row order already carry the meaning.
                ExcludeSemantics(
                  child: CircleAvatar(
                    radius: 14,
                    backgroundColor: AppColors.sky.withValues(alpha: 0.5),
                    foregroundColor: Theme.of(context).colorScheme.primary,
                    child: Text(
                      '${index + 1}',
                      style: const TextStyle(
                        fontSize: 12, fontWeight: FontWeight.w700),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        student.fullName,
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          color: context.tokens.ink,
                        ),
                      ),
                      Text(
                        student.permanentCode,
                        style: TextStyle(
                          color: context.tokens.muted,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  icon: Icon(
                    (mark.notes ?? '').isEmpty
                        ? Icons.note_add_outlined
                        : Icons.note_alt,
                    color: (mark.notes ?? '').isEmpty
                        ? context.tokens.muted
                        : AppColors.gold,
                  ),
                  onPressed: onNotes,
                  tooltip: 'ملاحظات',
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                // Day 13 — use the *Ink text-safe siblings so unselected
                // pills stop washing out against their own tinted bg.
                Expanded(child: _pill(AttendanceStatus.present, AppColors.successInk)),
                const SizedBox(width: 6),
                Expanded(child: _pill(AttendanceStatus.absent, AppColors.dangerInk)),
                const SizedBox(width: 6),
                Expanded(child: _pill(AttendanceStatus.late, AppColors.goldInk)),
              ],
            ),
          ],
        ),
        ),
      ),
    );
  }

  Widget _pill(AttendanceStatus s, Color c) {
    final selected = mark.status == s;
    // Day 12 — Semantics(button+selected) for TalkBack + minHeight:48 for
    // ≥48-dp touch target. This is the most-tapped control in the teacher
    // app; the old ~30-dp pill was uncomfortable even with a finger.
    return Semantics(
      button: true,
      selected: selected,
      label: s.labelAr,
      excludeSemantics: true,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 48),
        child: InkWell(
          onTap: () => onStatus(s),
          borderRadius: BorderRadius.circular(6),
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 12),
            decoration: BoxDecoration(
              color: selected ? c : c.withValues(alpha: 0.08),
              border: Border.all(color: c, width: selected ? 0 : 1),
              borderRadius: BorderRadius.circular(6),
            ),
            alignment: Alignment.center,
            child: Text(
              s.labelAr,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: selected ? Colors.white : c,
                fontWeight: FontWeight.w700,
                fontSize: 14,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _swipeBg(Color color, Alignment align, IconData icon) => Container(
        color: color.withValues(alpha: 0.9),
        alignment: align,
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: Icon(icon, color: Colors.white, size: 28),
      );
}

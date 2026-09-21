import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/courses_repository.dart';

/// [STU] My Courses — 2-column grid from `/student/courses`.
class CoursesScreen extends ConsumerWidget {
  const CoursesScreen({super.key});

  static const _accentBySubject = <String, Color>{
    'الرياضيات': ManasetyBrand.navy,
    'الفيزياء':  ManasetyBrand.cyan,
    'الكيمياء':  ManasetyBrand.warning,
    'الأحياء':   ManasetyBrand.success,
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(coursesListProvider);
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('مقرّراتي')),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(coursesListProvider.future),
        child: async.when(
          data: (rows) => rows.isEmpty
              ? _empty()
              : GridView.builder(
                  padding: const EdgeInsets.all(16),
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 2, mainAxisSpacing: 12,
                    crossAxisSpacing: 12, childAspectRatio: 0.85,
                  ),
                  itemCount: rows.length,
                  itemBuilder: (_, i) => _CourseCard(row: rows[i],
                    accent: _accentBySubject[rows[i].subject ?? ''] ?? ManasetyBrand.blue,
                    onTap: () => context.push('/courses/${rows[i].id}'),
                  ),
                ),
          loading: () => _skeleton(),
          error: (e, _) => _error(e, () => ref.invalidate(coursesListProvider)),
        ),
      ),
    );
  }

  Widget _empty() => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(mainAxisSize: MainAxisSize.min, children: const [
        Icon(Icons.menu_book_rounded, size: 72, color: ManasetyBrand.outline),
        SizedBox(height: 12),
        Text('لا مقرّرات مسجّلة بعد',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        SizedBox(height: 6),
        Text('ستظهر مقرّراتك هنا فور اعتماد الفصل الدراسي.',
          style: TextStyle(color: ManasetyBrand.onSurfaceVariant), textAlign: TextAlign.center),
      ]),
    ),
  );

  Widget _skeleton() => GridView.builder(
    padding: const EdgeInsets.all(16),
    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
      crossAxisCount: 2, mainAxisSpacing: 12, crossAxisSpacing: 12, childAspectRatio: 0.85),
    itemCount: 6,
    itemBuilder: (_, __) => Container(decoration: BoxDecoration(
      color: ManasetyBrand.surfaceContainerLow,
      borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl))),
  );

  Widget _error(Object e, VoidCallback retry) => ListView(children: [
    const SizedBox(height: 80),
    const Icon(Icons.wifi_off_rounded, size: 64, color: ManasetyBrand.outline),
    const SizedBox(height: 12),
    Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
    const SizedBox(height: 16),
    Center(child: TextButton.icon(onPressed: retry,
      icon: const Icon(Icons.refresh_rounded), label: const Text('حاول مرة أخرى'))),
  ]);
}

class _CourseCard extends StatelessWidget {
  const _CourseCard({required this.row, required this.accent, required this.onTap});
  final CourseBrief row;
  final Color accent;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: ManasetyBrand.surfaceContainerLowest,
      borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
      elevation: 0,
      child: InkWell(
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
        onTap: onTap,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            height: 84,
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.12),
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(ManasetyBrand.radius2xl),
                topRight: Radius.circular(ManasetyBrand.radius2xl),
              ),
            ),
            child: Center(child: Icon(Icons.menu_book_rounded, color: accent, size: 40)),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(row.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
              const SizedBox(height: 4),
              Text(row.teacher ?? row.subject ?? '',
                maxLines: 1, overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
              const SizedBox(height: 8),
              Text('${row.totalLessons} درس',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: accent)),
            ]),
          ),
        ]),
      ),
    );
  }
}

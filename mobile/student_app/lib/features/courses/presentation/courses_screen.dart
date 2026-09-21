import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';

/// [STU] My Courses / مقرّراتي — 2-column grid of course cards.
///
/// This is a stub that renders the design shell with 6 mock cards.
/// The real data fetch happens in `courses_repository.dart` once the
/// backend endpoint `/student/courses` lands.
class CoursesScreen extends StatelessWidget {
  const CoursesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final subjects = const [
      ('الرياضيات',        ManasetyBrand.navy,    Icons.calculate_rounded, 'د. أحمد ماجد', 0.65),
      ('الفيزياء',         ManasetyBrand.cyan,    Icons.science_rounded,   'د. ماجد الدوسري', 0.42),
      ('الكيمياء',         ManasetyBrand.warning, Icons.biotech_rounded,   'د. سارة الكندري', 0.78),
      ('الأحياء',          ManasetyBrand.success, Icons.eco_rounded,       'د. ليلى المطيري', 0.55),
      ('اللغة الإنجليزية',  ManasetyBrand.blue,    Icons.language_rounded,  'أ. رند العنزي',   0.85),
      ('التربية الإسلامية', Color(0xFF6366F1),     Icons.mosque_rounded,    'أ. خالد الشمري',  0.30),
    ];
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('مقرّراتي')),
      body: GridView.builder(
        padding: const EdgeInsets.all(16),
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2, mainAxisSpacing: 12, crossAxisSpacing: 12, childAspectRatio: 0.85,
        ),
        itemCount: subjects.length,
        itemBuilder: (_, i) {
          final (name, color, icon, teacher, progress) = subjects[i];
          return _CourseCard(name: name, color: color, icon: icon, teacher: teacher, progress: progress);
        },
      ),
    );
  }
}

class _CourseCard extends StatelessWidget {
  const _CourseCard({
    required this.name, required this.color, required this.icon,
    required this.teacher, required this.progress,
  });
  final String name; final Color color; final IconData icon;
  final String teacher; final double progress;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
        boxShadow: ManasetyBrand.shadowDefault,
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          height: 84,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.12),
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(ManasetyBrand.radius2xl),
              topRight: Radius.circular(ManasetyBrand.radius2xl),
            ),
          ),
          child: Center(child: Icon(icon, color: color, size: 40)),
        ),
        Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
            const SizedBox(height: 4),
            Text(teacher, style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(child: ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: LinearProgressIndicator(
                  value: progress,
                  minHeight: 6,
                  backgroundColor: ManasetyBrand.surfaceContainerLow,
                  valueColor: AlwaysStoppedAnimation(color),
                ),
              )),
              const SizedBox(width: 6),
              Text('${(progress * 100).round()}%',
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.navy)),
            ]),
          ]),
        ),
      ]),
    );
  }
}

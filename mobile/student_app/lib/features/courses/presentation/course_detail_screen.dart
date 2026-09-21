import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/courses_repository.dart';

class CourseDetailScreen extends ConsumerWidget {
  const CourseDetailScreen({required this.courseId, super.key});
  final int courseId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(courseDetailProvider(courseId));
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: async.whenOrNull(data: (c) => Text(c.title)) ?? const Text('المقرّر')),
      body: async.when(
        data: (c) => ListView(padding: const EdgeInsets.all(16), children: [
          _Hero(course: c),
          const SizedBox(height: 24),
          const Text('المحتوى',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
          const SizedBox(height: 8),
          for (final u in c.units) _UnitCard(unit: u),
          if (c.orphanLessons.isNotEmpty) _OrphanCard(lessons: c.orphanLessons),
        ]),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.course});
  final CourseDetail course;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: ManasetyBrand.primaryGradient,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(course.title,
          style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800)),
        const SizedBox(height: 6),
        Row(children: [
          const Icon(Icons.person_rounded, color: Colors.white70, size: 14),
          const SizedBox(width: 6),
          Text(course.teacher ?? course.subject ?? '',
            style: const TextStyle(color: Colors.white70)),
        ]),
      ]),
    );
  }
}

class _UnitCard extends StatelessWidget {
  const _UnitCard({required this.unit});
  final UnitBlock unit;
  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
      ),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          title: Text(unit.title, style: const TextStyle(fontWeight: FontWeight.w700)),
          initiallyExpanded: true,
          children: [for (final l in unit.lessons) _LessonRow(lesson: l)],
        ),
      ),
    );
  }
}

class _OrphanCard extends StatelessWidget {
  const _OrphanCard({required this.lessons});
  final List<LessonBrief> lessons;
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl)),
      child: Column(children: [
        const Padding(padding: EdgeInsets.all(12),
          child: Align(alignment: AlignmentDirectional.centerStart,
            child: Text('دروس عامة', style: TextStyle(fontWeight: FontWeight.w700)))),
        for (final l in lessons) _LessonRow(lesson: l),
      ]),
    );
  }
}

class _LessonRow extends StatelessWidget {
  const _LessonRow({required this.lesson});
  final LessonBrief lesson;
  @override
  Widget build(BuildContext context) {
    IconData icon;
    Color tone;
    switch (lesson.kind) {
      case 'video': icon = Icons.play_circle_rounded; tone = ManasetyBrand.error; break;
      case 'pdf':   icon = Icons.picture_as_pdf_rounded; tone = ManasetyBrand.warning; break;
      case 'quiz':  icon = Icons.quiz_rounded; tone = ManasetyBrand.warning; break;
      case 'embed': icon = Icons.code_rounded; tone = ManasetyBrand.blue; break;
      default:      icon = Icons.article_rounded; tone = ManasetyBrand.navy;
    }
    return ListTile(
      leading: Icon(icon, color: tone),
      title: Text(lesson.title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
      trailing: lesson.durationMinutes == null ? null :
        Text('${lesson.durationMinutes} د',
          style: const TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 12)),
      onTap: () => context.push('/lessons/${lesson.id}'),
    );
  }
}

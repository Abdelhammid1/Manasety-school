import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../data/courses_repository.dart';

/// Lesson viewer — the same shell handles every kind:
///   text  → renders body
///   video → gradient placeholder + open-external button (full player
///           lands with a video_player integration later)
///   pdf   → same placeholder + open/download
///   link/embed → open-external button
class LessonViewerScreen extends ConsumerWidget {
  const LessonViewerScreen({required this.lessonId, super.key});
  final int lessonId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(lessonViewProvider(lessonId));
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: async.whenOrNull(data: (l) => Text(l.title)) ?? const Text('الدرس')),
      body: async.when(
        data: (l) => ListView(padding: const EdgeInsets.all(16), children: [
          _Media(lesson: l),
          const SizedBox(height: 16),
          if (l.body.isNotEmpty) Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: ManasetyBrand.surfaceContainerLowest,
              borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
            ),
            child: Text(l.body,
              style: const TextStyle(fontSize: 14, height: 1.6, color: ManasetyBrand.onSurface)),
          ),
        ]),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
      ),
    );
  }
}

class _Media extends StatelessWidget {
  const _Media({required this.lesson});
  final LessonView lesson;
  @override
  Widget build(BuildContext context) {
    if (lesson.kind == 'text' || (lesson.mediaUrl ?? '').isEmpty) {
      return const SizedBox.shrink();
    }
    IconData icon;
    String cta;
    switch (lesson.kind) {
      case 'video': icon = Icons.play_circle_rounded; cta = 'شغّل الفيديو'; break;
      case 'pdf':   icon = Icons.picture_as_pdf_rounded; cta = 'افتح الملف'; break;
      case 'embed': icon = Icons.code_rounded; cta = 'افتح المحتوى'; break;
      default:      icon = Icons.link_rounded; cta = 'افتح الرابط';
    }
    return Container(
      height: 180,
      decoration: BoxDecoration(
        gradient: ManasetyBrand.primaryGradient,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
      ),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Icon(icon, size: 64, color: Colors.white),
        const SizedBox(height: 8),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 24),
          child: SizedBox(width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: () async {
                final uri = Uri.tryParse(lesson.mediaUrl!);
                if (uri != null) await launchUrl(uri, mode: LaunchMode.externalApplication);
              },
              icon: const Icon(Icons.open_in_new_rounded),
              label: Text(cta),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: ManasetyBrand.navy,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl)),
              ),
            ),
          ),
        ),
      ]),
    );
  }
}

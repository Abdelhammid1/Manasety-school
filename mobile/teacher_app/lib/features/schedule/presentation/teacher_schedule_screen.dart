import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../data/schedule_repository.dart';

class TeacherScheduleScreen extends ConsumerWidget {
  const TeacherScheduleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final slots = ref.watch(teacherScheduleProvider);
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(teacherScheduleProvider);
        await ref.read(teacherScheduleProvider.future);
      },
      child: AsyncValueWidget(
        value: slots,
        onRetry: () => ref.invalidate(teacherScheduleProvider),
        // hide teacher names (the teacher is the user themselves)
        data: (list) => WeeklyScheduleGrid(slots: list, showTeacher: false),
      ),
    );
  }
}

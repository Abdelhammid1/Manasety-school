import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../data/schedule_repository.dart';

class ChildScheduleTab extends ConsumerWidget {
  final int childId;
  const ChildScheduleTab({super.key, required this.childId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final slots = ref.watch(childScheduleProvider(childId));
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(childScheduleProvider(childId));
        await ref.read(childScheduleProvider(childId).future);
      },
      child: AsyncValueWidget(
        value: slots,
        onRetry: () => ref.invalidate(childScheduleProvider(childId)),
        data: (list) => WeeklyScheduleGrid(slots: list),
      ),
    );
  }
}

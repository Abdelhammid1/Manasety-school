import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';

/// Uses the shared [AttendanceDonut] and [AttendanceMonthGrid] widgets
/// from `manasety_ui` once wired to `/student/attendance`. This stub
/// draws the shell only.
class AttendanceScreen extends StatelessWidget {
  const AttendanceScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('حضوري')),
      body: const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('سيظهر سجل حضورك الشهري هنا.',
            style: TextStyle(color: ManasetyBrand.onSurfaceVariant)),
        ),
      ),
    );
  }
}

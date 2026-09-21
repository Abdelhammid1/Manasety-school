import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';

/// Placeholder — full grid will consume the shared `WeeklyScheduleGrid`
/// widget from manasety_ui once the `/student/schedule` endpoint lands.
class TimetableScreen extends StatelessWidget {
  const TimetableScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('جدولي الأسبوعي')),
      body: const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.calendar_month_rounded, size: 72, color: ManasetyBrand.outline),
            SizedBox(height: 12),
            Text('الجدول قيد التحميل',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
            SizedBox(height: 6),
            Text('سيظهر جدولك الأسبوعي هنا فور تحديث بيانات الفصل.',
              style: TextStyle(color: ManasetyBrand.onSurfaceVariant), textAlign: TextAlign.center),
          ]),
        ),
      ),
    );
  }
}

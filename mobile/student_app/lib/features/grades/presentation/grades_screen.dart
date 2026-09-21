import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';

class GradesScreen extends StatelessWidget {
  const GradesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('تقاريري')),
      body: const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('سيظهر تقرير الفصل هنا فور إغلاق النتائج.',
            style: TextStyle(color: ManasetyBrand.onSurfaceVariant)),
        ),
      ),
    );
  }
}

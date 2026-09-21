import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';

class AnnouncementsScreen extends StatelessWidget {
  const AnnouncementsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('الإعلانات')),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: 6,
        itemBuilder: (_, i) => Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: ManasetyBrand.surfaceContainerLowest,
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
            border: Border(right: BorderSide(
              color: i < 2 ? ManasetyBrand.navy : Colors.transparent,
              width: 3,
            )),
          ),
          child: Row(children: [
            const CircleAvatar(
              radius: 20,
              backgroundColor: ManasetyBrand.surfaceContainerLow,
              child: Icon(Icons.campaign_rounded, color: ManasetyBrand.navy),
            ),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('إعلان الفصل الدراسي #${i + 1}',
                style: TextStyle(
                  fontWeight: i < 2 ? FontWeight.w800 : FontWeight.w600,
                  fontSize: 14, color: ManasetyBrand.onSurface,
                )),
              const SizedBox(height: 4),
              const Text('د. أحمد ماجد · الرياضيات',
                style: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 12)),
            ])),
            const Text('منذ ٢ س',
              style: TextStyle(color: ManasetyBrand.outline, fontSize: 11)),
          ]),
        ),
      ),
    );
  }
}

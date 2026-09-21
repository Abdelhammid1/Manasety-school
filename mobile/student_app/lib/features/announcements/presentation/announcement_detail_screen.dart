import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../shared/api/misc_repositories.dart';

class AnnouncementDetailScreen extends ConsumerWidget {
  const AnnouncementDetailScreen({required this.announcementId, super.key});
  final int announcementId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(announcementDetailProvider(announcementId));
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('الإعلان')),
      body: async.when(
        data: (a) => ListView(padding: const EdgeInsets.all(16), children: [
          Container(padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: ManasetyBrand.surfaceContainerLowest,
              borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
              boxShadow: ManasetyBrand.shadowDefault,
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const CircleAvatar(radius: 20,
                  backgroundColor: ManasetyBrand.surfaceContainerLow,
                  child: Icon(Icons.campaign_rounded, color: ManasetyBrand.navy)),
                const SizedBox(width: 12),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(a.author ?? 'إدارة المدرسة',
                    style: const TextStyle(fontWeight: FontWeight.w700)),
                  if (a.createdAt != null) Text(a.createdAt!,
                    style: const TextStyle(color: ManasetyBrand.outline, fontSize: 12)),
                ])),
              ]),
              const SizedBox(height: 16),
              Text(a.title, style: const TextStyle(
                fontSize: 20, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
              const SizedBox(height: 12),
              Text(a.body, style: const TextStyle(fontSize: 14, height: 1.7)),
            ]),
          ),
          const SizedBox(height: 16),
          Container(padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: ManasetyBrand.surfaceContainerLow,
              borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl)),
            child: Row(children: const [
              Icon(Icons.check_circle_rounded, color: ManasetyBrand.success, size: 16),
              SizedBox(width: 8),
              Text('تمّت القراءة · تم الإرسال إلى ولي أمرك',
                style: TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
            ]),
          ),
        ]),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
      ),
    );
  }
}

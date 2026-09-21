import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../shared/api/misc_repositories.dart';

class AnnouncementsScreen extends ConsumerWidget {
  const AnnouncementsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(announcementsProvider);
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('الإعلانات')),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(announcementsProvider.future),
        child: async.when(
          data: (rows) {
            if (rows.isEmpty) return _empty();
            return ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: rows.length,
              itemBuilder: (_, i) => Material(
                color: ManasetyBrand.surfaceContainerLowest,
                borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
                child: InkWell(
                  borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
                  onTap: () => context.push('/announcements/${rows[i].id}'),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(14),
                    child: Row(children: [
                      const CircleAvatar(radius: 20, backgroundColor: ManasetyBrand.surfaceContainerLow,
                        child: Icon(Icons.campaign_rounded, color: ManasetyBrand.navy)),
                      const SizedBox(width: 12),
                      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(rows[i].title,
                          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
                        const SizedBox(height: 4),
                        Text(rows[i].author ?? '',
                          style: const TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 12)),
                      ])),
                    ]),
                  ),
                ),
              ),
            );
          },
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
        ),
      ),
    );
  }

  Widget _empty() => Center(child: Padding(padding: const EdgeInsets.all(24),
    child: Column(mainAxisSize: MainAxisSize.min, children: const [
      Icon(Icons.campaign_outlined, size: 72, color: ManasetyBrand.outline),
      SizedBox(height: 12),
      Text('لا إعلانات جديدة', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
    ])));
}

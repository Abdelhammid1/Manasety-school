import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../children/data/children_repository.dart';
import '../data/pickup_repository.dart';

/// نداء لاستلام الطالب — parent-side. Big green button per child;
/// tap → server records a PickupCall + fans out a notification to the
/// student and the responsible teacher.
class PickupScreen extends ConsumerWidget {
  const PickupScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final children = ref.watch(childrenProvider);
    final active = ref.watch(activePickupCallsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('نداء لاستلام الطالب'),
        actions: [
          IconButton(
            tooltip: 'تحديث',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(activePickupCallsProvider),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(activePickupCallsProvider),
        child: SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _HeroBanner(theme: theme),
              const SizedBox(height: 16),
              active.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(vertical: 8),
                  child: LinearProgressIndicator(),
                ),
                error: (e, _) => _ErrorCard(message: e.toString()),
                data: (calls) => calls.isEmpty
                    ? const SizedBox.shrink()
                    : _ActiveCallsSection(calls: calls),
              ),
              const SizedBox(height: 16),
              const Text('أبناؤك',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
              const SizedBox(height: 8),
              children.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (e, _) => _ErrorCard(message: e.toString()),
                data: (list) {
                  if (list.isEmpty) {
                    return const Padding(
                      padding: EdgeInsets.symmetric(vertical: 24),
                      child: Text('لا يوجد أبناء مرتبطون بحسابك.'),
                    );
                  }
                  return Column(
                    children: [
                      for (final c in list)
                        _CallCard(
                          childId: c.id,
                          childName: c.fullName,
                          code: c.permanentCode,
                        ),
                    ],
                  );
                },
              ),
              const SizedBox(height: 16),
              Card(
                color: theme.colorScheme.surfaceContainerLow,
                child: const Padding(
                  padding: EdgeInsets.all(12),
                  child: ListTile(
                    leading: Icon(Icons.info_outline),
                    title: Text('كيف تعمل خدمة النداء؟'),
                    subtitle: Text(
                      'عند الضغط على النداء يصل إشعار فوري إلى ابنك/ابنتك والمعلم المسؤول عن الشعبة. عند تأكيد «تم الاستلام» يُغلق النداء تلقائياً.',
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _HeroBanner extends StatelessWidget {
  const _HeroBanner({required this.theme});
  final ThemeData theme;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        gradient: const LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [Color(0xFF059669), Color(0xFF0D9488), Color(0xFF10B981)],
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.2),
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Icon(Icons.directions_car,
                color: Colors.white, size: 32),
          ),
          const SizedBox(width: 12),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('نداء لاستلام الطالب',
                    style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 20)),
                SizedBox(height: 4),
                Text(
                  'اضغط عند وصولك خارج المدرسة — سيصل الإشعار فوراً للطالب والمعلم المسؤول.',
                  style: TextStyle(color: Colors.white70, fontSize: 13),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CallCard extends ConsumerStatefulWidget {
  const _CallCard({
    required this.childId,
    required this.childName,
    required this.code,
  });
  final int childId;
  final String childName;
  final String? code;
  @override
  ConsumerState<_CallCard> createState() => _CallCardState();
}

class _CallCardState extends ConsumerState<_CallCard> {
  String _gate = 'البوابة الرئيسية';
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: Theme.of(context)
                        .colorScheme
                        .primaryContainer
                        .withValues(alpha: 0.4),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(Icons.school, color: Colors.blueGrey),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(widget.childName,
                          style: const TextStyle(
                              fontWeight: FontWeight.bold, fontSize: 16)),
                      if (widget.code != null && widget.code!.isNotEmpty)
                        Text(widget.code!,
                            style: const TextStyle(
                                color: Colors.grey, fontSize: 12),
                            textDirection: TextDirection.ltr),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _gate,
              decoration: const InputDecoration(labelText: 'البوابة'),
              items: const [
                DropdownMenuItem(
                    value: 'البوابة الرئيسية', child: Text('البوابة الرئيسية')),
                DropdownMenuItem(
                    value: 'بوابة الحافلات', child: Text('بوابة الحافلات')),
                DropdownMenuItem(
                    value: 'بوابة الروضة', child: Text('بوابة الروضة')),
              ],
              onChanged: (v) => setState(() => _gate = v ?? _gate),
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 64,
              child: FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF10B981),
                  shape: const StadiumBorder(),
                ),
                onPressed: _busy ? null : _sendCall,
                icon: _busy
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                            color: Colors.white, strokeWidth: 2))
                    : const Icon(Icons.campaign, size: 28),
                label: const Text('نداء',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _sendCall() async {
    setState(() => _busy = true);
    try {
      final repo = ref.read(pickupRepositoryProvider);
      await repo.call(studentId: widget.childId, gate: _gate);
      ref.invalidate(activePickupCallsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('تم إرسال النداء — بانتظار خروج ${widget.childName}.'),
        ));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('تعذّر إرسال النداء: $e'),
        ));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

class _ActiveCallsSection extends ConsumerWidget {
  const _ActiveCallsSection({required this.calls});
  final List<PickupCallDto> calls;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Row(children: [
          Icon(Icons.notifications_active, color: Color(0xFF10B981)),
          SizedBox(width: 8),
          Text('نداء جارٍ الآن',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
        ]),
        const SizedBox(height: 8),
        for (final c in calls)
          Card(
            color: const Color(0xFFECFDF5),
            child: ListTile(
              leading: const CircleAvatar(
                backgroundColor: Color(0xFF10B981),
                child: Icon(Icons.directions_car, color: Colors.white),
              ),
              title: Text(c.studentName),
              subtitle: Text(
                  '${c.gate ?? ''} · بدأ منذ ${c.waitedMin} دقيقة'
                  '${c.seenByTeacher ? ' · شاهد المعلم' : ''}'
                  '${c.seenByStudent ? ' · شاهد الطالب' : ''}'),
              trailing: TextButton(
                onPressed: () async {
                  try {
                    await ref.read(pickupRepositoryProvider).release(c.id);
                    ref.invalidate(activePickupCallsProvider);
                  } catch (_) {}
                },
                child: const Text('تم الاستلام'),
              ),
            ),
          ),
      ],
    );
  }
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message});
  final String message;
  @override
  Widget build(BuildContext context) => Card(
        color: Theme.of(context).colorScheme.errorContainer,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Text(message,
              style: TextStyle(
                  color: Theme.of(context).colorScheme.onErrorContainer)),
        ),
      );
}

import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';

class AssignmentsScreen extends StatefulWidget {
  const AssignmentsScreen({super.key});

  @override
  State<AssignmentsScreen> createState() => _AssignmentsScreenState();
}

class _AssignmentsScreenState extends State<AssignmentsScreen> {
  int _tab = 0;   // 0 = واجبات, 1 = اختبارات

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('واجباتي واختباراتي')),
      body: Column(children: [
        // Segmented control.
        Padding(
          padding: const EdgeInsets.all(16),
          child: Container(
            decoration: BoxDecoration(
              color: ManasetyBrand.surfaceContainerLow,
              borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
            ),
            padding: const EdgeInsets.all(4),
            child: Row(children: [
              _segment('واجبات',  0),
              _segment('اختبارات', 1),
            ]),
          ),
        ),
        Expanded(child: _tab == 0 ? _list('لا واجبات في التصفية الحالية.') : _list('لا اختبارات في التصفية الحالية.')),
      ]),
    );
  }

  Widget _segment(String label, int idx) {
    final active = _tab == idx;
    return Expanded(
      child: GestureDetector(
        onTap: () => setState(() => _tab = idx),
        child: Container(
          height: 40,
          decoration: BoxDecoration(
            gradient: active ? ManasetyBrand.primaryGradient : null,
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusLg),
          ),
          alignment: Alignment.center,
          child: Text(label, style: TextStyle(
            color: active ? Colors.white : ManasetyBrand.onSurfaceVariant,
            fontWeight: FontWeight.w700,
          )),
        ),
      ),
    );
  }

  Widget _list(String emptyText) {
    // Stub: real repository will paginate. For now, show 6 mock rows +
    // an empty tail so the design pattern is visible.
    final items = List.generate(6, (i) => (
      title: 'واجب #${i + 1} — الرياضيات',
      due: i.isEven ? 'يستحق: ٥ نوفمبر' : 'يستحق: ٧ نوفمبر',
      status: ['لم أبدأ', 'قيد الحل', 'سُلّم', 'مصحّح 92%'][i % 4],
      tone: [ManasetyBrand.blue, ManasetyBrand.warning, ManasetyBrand.success, ManasetyBrand.success][i % 4],
    ));
    return ListView.builder(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      itemCount: items.length,
      itemBuilder: (_, i) {
        final it = items[i];
        return Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: ManasetyBrand.surfaceContainerLowest,
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
            border: Border.all(color: ManasetyBrand.outline.withValues(alpha: 0.2)),
          ),
          child: Row(children: [
            CircleAvatar(
              radius: 20,
              backgroundColor: it.tone.withValues(alpha: 0.12),
              child: Icon(Icons.assignment_rounded, color: it.tone, size: 20),
            ),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(it.title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
              const SizedBox(height: 4),
              Text(it.due, style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
            ])),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: it.tone.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(999)),
              child: Text(it.status, style: TextStyle(color: it.tone, fontSize: 11, fontWeight: FontWeight.w700)),
            ),
          ]),
        );
      },
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/assignments_repository.dart';

class AssignmentAttemptScreen extends ConsumerStatefulWidget {
  const AssignmentAttemptScreen({required this.assignmentId, super.key});
  final int assignmentId;

  @override
  ConsumerState<AssignmentAttemptScreen> createState() => _State();
}

class _State extends ConsumerState<AssignmentAttemptScreen> {
  final Map<int, dynamic> _answers = {};
  int _index = 0;
  final _bodyCtrl = TextEditingController();
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(assignmentDetailProvider(widget.assignmentId));
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(
        title: async.whenOrNull(data: (a) => Text(a.title)) ?? const Text('واجب'),
        actions: [
          IconButton(icon: const Icon(Icons.save_alt_rounded), onPressed: () {}),
        ],
      ),
      body: async.when(
        data: (a) {
          final total = a.questions.length;
          final progress = total == 0 ? 1.0 : (_index + 1) / total;
          return Column(children: [
            LinearProgressIndicator(
              value: progress,
              backgroundColor: ManasetyBrand.surfaceContainerLow,
              valueColor: const AlwaysStoppedAnimation(ManasetyBrand.navy),
            ),
            const SizedBox(height: 8),
            if (total > 0) Text('السؤال ${_index + 1} من $total',
              style: const TextStyle(fontWeight: FontWeight.w700)),
            Expanded(child: total == 0
              ? _FreeFormBody(controller: _bodyCtrl, instructions: a.instructions)
              : _QuestionCard(question: a.questions[_index],
                selectedChoiceId: _answers[a.questions[_index].id] is int
                    ? _answers[a.questions[_index].id] as int : null,
                onSelect: (cid) => setState(() {
                  _answers[a.questions[_index].id] = cid;
                }))),
            _bottomBar(context, a, total),
          ]);
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
      ),
    );
  }

  Widget _bottomBar(BuildContext context, AssignmentDetail a, int total) {
    final isLast = _index >= total - 1;
    return SafeArea(child: Padding(padding: const EdgeInsets.all(16),
      child: Row(children: [
        OutlinedButton(
          onPressed: _index == 0 ? null : () => setState(() => _index--),
          child: const Text('السابق'),
        ),
        const SizedBox(width: 12),
        Expanded(child: Container(
          height: 48,
          decoration: BoxDecoration(gradient: _busy ? null : ManasetyBrand.primaryGradient,
            color: _busy ? ManasetyBrand.outline : null,
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl)),
          child: Material(color: Colors.transparent, child: InkWell(
            onTap: _busy ? null : () async {
              if (isLast || total == 0) {
                await _submit(a);
                if (!context.mounted) return;
                context.pop();
              } else {
                setState(() => _index++);
              }
            },
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
            child: Center(child: Text(
              isLast || total == 0 ? (_busy ? 'جارٍ التسليم…' : 'سلّم') : 'التالي',
              style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
            )),
          )),
        )),
      ]),
    ));
  }

  Future<void> _submit(AssignmentDetail a) async {
    setState(() => _busy = true);
    try {
      await ref.read(assignmentsRepositoryProvider).submitAssignment(
        widget.assignmentId, answers: _answers, body: _bodyCtrl.text,
      );
      ref.invalidate(assignmentsListProvider);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('تم التسليم بنجاح ✅')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e is ApiException ? e.message : 'تعذّر التسليم')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() { _bodyCtrl.dispose(); super.dispose(); }
}

class _FreeFormBody extends StatelessWidget {
  const _FreeFormBody({required this.controller, required this.instructions});
  final TextEditingController controller;
  final String instructions;
  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.all(16), children: [
      if (instructions.isNotEmpty) Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: ManasetyBrand.surfaceContainerLow,
          borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl)),
        child: Text(instructions, style: const TextStyle(height: 1.6)),
      ),
      const SizedBox(height: 16),
      TextField(controller: controller, maxLines: 10,
        decoration: InputDecoration(
          hintText: 'اكتب إجابتك هنا…',
          filled: true, fillColor: ManasetyBrand.surfaceContainerLowest,
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
            borderSide: BorderSide.none),
        ),
      ),
    ]);
  }
}

class _QuestionCard extends StatelessWidget {
  const _QuestionCard({required this.question, required this.selectedChoiceId,
    required this.onSelect});
  final AttemptQuestion question;
  final int? selectedChoiceId;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.all(16), children: [
      Container(padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: ManasetyBrand.surfaceContainerLowest,
          borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
          boxShadow: ManasetyBrand.shadowDefault,
        ),
        child: Text(question.prompt,
          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, height: 1.6))),
      const SizedBox(height: 16),
      for (int i = 0; i < question.choices.length; i++)
        Padding(padding: const EdgeInsets.only(bottom: 8),
          child: _Choice(index: i, choice: question.choices[i],
            selected: selectedChoiceId == question.choices[i].id,
            onTap: () => onSelect(question.choices[i].id))),
    ]);
  }
}

class _Choice extends StatelessWidget {
  const _Choice({required this.index, required this.choice,
    required this.selected, required this.onTap});
  final int index;
  final ChoiceOption choice;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final letters = const ['أ', 'ب', 'ج', 'د', 'هـ'];
    return Material(
      color: ManasetyBrand.surfaceContainerLowest,
      borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
      child: InkWell(borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        onTap: onTap,
        child: Container(padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            border: Border.all(
              color: selected ? ManasetyBrand.navy : ManasetyBrand.outline.withValues(alpha: 0.3),
              width: selected ? 2 : 1,
            ),
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
            color: selected ? ManasetyBrand.navy.withValues(alpha: 0.05) : null,
          ),
          child: Row(children: [
            CircleAvatar(radius: 14,
              backgroundColor: selected ? ManasetyBrand.navy : ManasetyBrand.surfaceContainer,
              child: Text(letters[index % letters.length],
                style: TextStyle(color: selected ? Colors.white : ManasetyBrand.onSurface,
                  fontSize: 12, fontWeight: FontWeight.w700))),
            const SizedBox(width: 12),
            Expanded(child: Text(choice.label,
              style: TextStyle(fontSize: 14,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500))),
          ]),
        ),
      ),
    );
  }
}

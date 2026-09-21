import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/assignments_repository.dart';

class QuizAttemptScreen extends ConsumerStatefulWidget {
  const QuizAttemptScreen({required this.quizId, super.key});
  final int quizId;

  @override
  ConsumerState<QuizAttemptScreen> createState() => _State();
}

class _State extends ConsumerState<QuizAttemptScreen> {
  final Map<int, dynamic> _answers = {};
  int _index = 0;
  Duration? _remaining;
  Timer? _ticker;
  bool _busy = false;

  @override
  void dispose() { _ticker?.cancel(); super.dispose(); }

  void _startTimer(int minutes) {
    _remaining = Duration(minutes: minutes);
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() => _remaining = (_remaining ?? Duration.zero) - const Duration(seconds: 1));
      if ((_remaining?.inSeconds ?? 0) <= 0) {
        _ticker?.cancel();
        _submit();
      }
    });
  }

  Color _timerColor() {
    final s = _remaining?.inSeconds ?? 0;
    if (s <= 60) return ManasetyBrand.error;
    if (s <= 300) return ManasetyBrand.warning;
    return ManasetyBrand.navy;
  }

  Future<void> _submit() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final result = await ref.read(assignmentsRepositoryProvider)
          .submitQuiz(widget.quizId, answers: _answers);
      ref.invalidate(quizzesListProvider);
      if (!mounted) return;
      await showDialog(context: context, builder: (_) => AlertDialog(
        title: const Text('تم التسليم'),
        content: Text('درجتك: ${result['score']}%'),
        actions: [TextButton(onPressed: () => context.pop(),
          child: const Text('حسنًا'))],
      ));
      if (!mounted) return;
      context.pop();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(e is ApiException ? e.message : 'تعذّر التسليم')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(quizAttemptProvider(widget.quizId));
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(
        title: async.whenOrNull(data: (q) => Text(q.title)) ?? const Text('اختبار'),
        actions: [async.whenOrNull(data: (q) {
          // Start the timer on first frame.
          if (_ticker == null && q.durationMinutes != null && q.durationMinutes! > 0) {
            WidgetsBinding.instance.addPostFrameCallback((_) => _startTimer(q.durationMinutes!));
          }
          if (_remaining == null) return const SizedBox.shrink();
          final m = _remaining!.inMinutes.remainder(60).toString().padLeft(2, '0');
          final s = _remaining!.inSeconds.remainder(60).toString().padLeft(2, '0');
          return Container(margin: const EdgeInsetsDirectional.only(end: 12),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(color: _timerColor().withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(999)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.timer_rounded, color: _timerColor(), size: 16),
              const SizedBox(width: 4),
              Text('$m:$s', style: TextStyle(color: _timerColor(),
                fontFamily: 'monospace', fontWeight: FontWeight.w700)),
            ]),
          );
        }) ?? const SizedBox.shrink()],
      ),
      body: async.when(
        data: (q) {
          final total = q.questions.length;
          if (total == 0) return const Center(child: Text('لا أسئلة لهذا الاختبار.'));
          final question = q.questions[_index];
          return Column(children: [
            LinearProgressIndicator(value: (_index + 1) / total,
              backgroundColor: ManasetyBrand.surfaceContainerLow,
              valueColor: const AlwaysStoppedAnimation(ManasetyBrand.navy)),
            Expanded(child: ListView(padding: const EdgeInsets.all(16), children: [
              Text('السؤال ${_index + 1} من $total',
                style: const TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Container(padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: ManasetyBrand.surfaceContainerLowest,
                  borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
                ),
                child: Text(question.prompt,
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, height: 1.6))),
              const SizedBox(height: 16),
              for (int i = 0; i < question.choices.length; i++)
                _choice(question, i, question.choices[i]),
            ])),
            SafeArea(child: Padding(padding: const EdgeInsets.all(16),
              child: Row(children: [
                OutlinedButton(onPressed: _index == 0
                    ? null : () => setState(() => _index--),
                  child: const Text('السابق')),
                const SizedBox(width: 12),
                Expanded(child: Container(height: 48,
                  decoration: BoxDecoration(gradient: _busy ? null : ManasetyBrand.primaryGradient,
                    color: _busy ? ManasetyBrand.outline : null,
                    borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl)),
                  child: Material(color: Colors.transparent, child: InkWell(
                    borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
                    onTap: _busy ? null : () async {
                      if (_index >= total - 1) {
                        final ok = await showDialog<bool>(context: context, builder: (_) => AlertDialog(
                          title: const Text('سلّم الآن؟'),
                          content: const Text('بعد التسليم لا يمكنك التعديل.'),
                          actions: [
                            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('رجوع')),
                            TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('تأكيد')),
                          ],
                        ));
                        if (ok == true) await _submit();
                      } else {
                        setState(() => _index++);
                      }
                    },
                    child: Center(child: Text(
                      _index >= total - 1 ? (_busy ? 'جارٍ التسليم…' : 'سلّم') : 'التالي',
                      style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
                    )),
                  )),
                )),
              ]),
            )),
          ]);
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
      ),
    );
  }

  Widget _choice(AttemptQuestion question, int index, ChoiceOption choice) {
    final selected = _answers[question.id] == choice.id;
    final letters = const ['أ', 'ب', 'ج', 'د', 'هـ'];
    return Padding(padding: const EdgeInsets.only(bottom: 8),
      child: Material(color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        child: InkWell(borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
          onTap: () => setState(() => _answers[question.id] = choice.id),
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
      ),
    );
  }
}

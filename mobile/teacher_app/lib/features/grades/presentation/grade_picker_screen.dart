import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../../../shared/models/component.dart';
import '../../../shared/models/section_brief.dart';
import '../../../shared/models/term.dart';
import '../../sections/data/sections_repository.dart';
import '../data/grades_repository.dart';

/// 3-step picker: term → subject → component. Auto-advances if only one option.
class GradePickerScreen extends ConsumerStatefulWidget {
  final int sectionId;
  const GradePickerScreen({super.key, required this.sectionId});
  @override
  ConsumerState<GradePickerScreen> createState() => _GradePickerScreenState();
}

class _GradePickerScreenState extends ConsumerState<GradePickerScreen> {
  int? _termId;
  int? _subjectId;

  @override
  Widget build(BuildContext context) {
    final termsAsync = ref.watch(termsProvider);
    final sectionsAsync = ref.watch(sectionsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('رصد الدرجات')),
      body: AsyncValueWidget<List<Term>>(
        value: termsAsync,
        onRetry: () => ref.invalidate(termsProvider),
        data: (terms) {
          if (terms.isEmpty) {
            return const EmptyState(
              icon: Icons.event_busy,
              illustration: EmptyIllustration(kind: ManasetyEmpty.book),
              title: 'لا توجد فترات دراسية معرَّفة',
              description: 'اطلب من الإدارة إضافة الفترات الدراسية أولًا.',
            );
          }
          // Auto-select if only 1 term
          if (_termId == null && terms.length == 1) {
            WidgetsBinding.instance.addPostFrameCallback(
                (_) => setState(() => _termId = terms.first.id));
          }
          return AsyncValueWidget<List<SectionBrief>>(
            value: sectionsAsync,
            data: (sections) {
              // Day 12 hot-fix — replaced `throw Exception('no section')`
              // with a graceful EmptyState; a deep-link into the picker for a
              // section the user no longer teaches would previously crash.
              if (sections.isEmpty) {
                return const EmptyState(
                  icon: Icons.class_outlined,
                  illustration: EmptyIllustration(kind: ManasetyEmpty.classroom),
                  title: 'لا توجد فصول مسندة إليك',
                  description: 'اطلب من الإدارة إسناد فصل قبل رصد الدرجات.',
                );
              }
              final matches = sections.where((s) => s.id == widget.sectionId);
              final section = matches.isNotEmpty ? matches.first : sections.first;
              // Auto-select if only 1 subject
              if (_subjectId == null && section.subjects.length == 1) {
                WidgetsBinding.instance.addPostFrameCallback(
                    (_) => setState(() => _subjectId = section.subjects.first.id));
              }
              return ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  _stepHeader('1', 'الفترة الدراسية'),
                  Wrap(
                    spacing: 8, runSpacing: 8,
                    children: terms.map((t) => _chip(
                      label: t.name,
                      selected: _termId == t.id,
                      onTap: () => setState(() => _termId = t.id),
                    )).toList(),
                  ),
                  const SizedBox(height: 24),
                  _stepHeader('2', 'المادة'),
                  Wrap(
                    spacing: 8, runSpacing: 8,
                    children: section.subjects.map((s) => _chip(
                      label: s.name,
                      selected: _subjectId == s.id,
                      onTap: () => setState(() => _subjectId = s.id),
                    )).toList(),
                  ),
                  const SizedBox(height: 24),
                  if (_termId != null && _subjectId != null) ...[
                    _stepHeader('3', 'مكوّن التقييم'),
                    _componentsPicker(),
                  ],
                ],
              );
            },
          );
        },
      ),
    );
  }

  Widget _componentsPicker() {
    final args = (subjectId: _subjectId!, termId: _termId!);
    final compsAsync = ref.watch(componentsProvider(args));
    return AsyncValueWidget<List<AssessmentComponentBrief>>(
      value: compsAsync,
      onRetry: () => ref.invalidate(componentsProvider(args)),
      data: (comps) {
        if (comps.isEmpty) {
          return const EmptyState(
            icon: Icons.assignment_late_outlined,
            illustration: EmptyIllustration(kind: ManasetyEmpty.book),
            title: 'لم تُعرَّف مكوّنات لهذه المادة والفترة',
            description: 'اطلب من الإدارة إضافة مكونات التقييم أولًا.',
          );
        }
        return Wrap(
          spacing: 8, runSpacing: 8,
          children: comps.map((c) => Semantics(
            button: true,
            label: '${c.name} — من ${_fmt(c.maxScore)}',
            excludeSemantics: true,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 48),
              child: InkWell(
                onTap: () {
                  context.push(
                    '/sections/${widget.sectionId}/grades/entry'
                    '?term=$_termId&subject=$_subjectId&component=${c.id}'
                    '&name=${Uri.encodeQueryComponent(c.name)}&max=${c.maxScore}',
                  );
                },
                borderRadius: BorderRadius.circular(10),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  decoration: BoxDecoration(
                    color: AppColors.gold.withValues(alpha: 0.08),
                    border: Border.all(color: AppColors.gold, width: 1.4),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(c.name, style: const TextStyle(
                        fontWeight: FontWeight.w700, color: AppColors.goldDark)),
                      const SizedBox(width: 6),
                      Text('/${_fmt(c.maxScore)}', style: TextStyle(
                        color: context.tokens.muted, fontSize: 12)),
                    ],
                  ),
                ),
              ),
            ),
          )).toList(),
        );
      },
    );
  }

  Widget _stepHeader(String n, String label) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(
          children: [
            CircleAvatar(
              radius: 12, backgroundColor: AppColors.navy,
              foregroundColor: Colors.white,
              child: Text(n, style: const TextStyle(
                fontWeight: FontWeight.w800, fontSize: 12)),
            ),
            const SizedBox(width: 8),
            Text(label, style: TextStyle(
              fontWeight: FontWeight.w800, color: Theme.of(context).colorScheme.primary, fontSize: 15)),
          ],
        ),
      );

  Widget _chip({required String label, required bool selected, required VoidCallback onTap}) =>
      Semantics(
        button: true,
        selected: selected,
        label: label,
        excludeSemantics: true,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48),
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(16),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              decoration: BoxDecoration(
                color: selected ? AppColors.navy : context.tokens.surface,
                border: Border.all(
                  color: selected ? AppColors.navy : context.tokens.border,
                  width: selected ? 0 : 1,
                ),
                borderRadius: BorderRadius.circular(16),
              ),
              alignment: Alignment.center,
              child: Text(label, style: TextStyle(
                color: selected ? Colors.white : context.tokens.ink,
                fontWeight: FontWeight.w700, fontSize: 13,
              )),
            ),
          ),
        ),
      );

  String _fmt(double v) => v == v.toInt().toDouble() ? v.toInt().toString() : v.toString();
}

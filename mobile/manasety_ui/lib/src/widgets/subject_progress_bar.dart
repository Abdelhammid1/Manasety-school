import 'package:flutter/material.dart';

import '../theme/arabize.dart';
import '../theme/colors.dart';
import '../theme/subject_palette.dart';
import '../theme/tokens.dart';

/// One horizontal row per subject on the results screen: a subject-tinted
/// icon + the subject name + a fixed-width progress bar filled to the score
/// out of [maxScore], with a right-aligned Arabic-Indic score readout.
///
/// The bar's fill color is threshold-based (red < 50%, gold 50-70%, green ≥ 70%)
/// so a parent can read pass/borderline/fail at a glance without reading numbers.
class SubjectProgressBar extends StatelessWidget {
  /// Subject display name — hashed for its accent color + icon.
  final String subject;

  /// Score out of [maxScore]. Clamped 0..maxScore.
  final double score;

  /// Total possible score. Defaults to 100.
  final double maxScore;

  const SubjectProgressBar({
    super.key,
    required this.subject,
    required this.score,
    this.maxScore = 100,
  });

  double get _pct {
    if (maxScore <= 0) return 0;
    final r = score / maxScore;
    return r.clamp(0.0, 1.0);
  }

  Color _fillColor() {
    final p = _pct * 100;
    if (p >= 70) return AppColors.success;
    if (p >= 50) return AppColors.gold;
    return AppColors.danger;
  }

  /// Day 12 hot-fix — the score readout uses this instead of the bar-fill
  /// color; gold band now reads as `goldInk` (≈5:1 on white) instead of the
  /// washed-out `gold` that vanished into the surface.
  Color _scoreColor() {
    final p = _pct * 100;
    if (p >= 70) return AppColors.success;
    if (p >= 50) return AppColors.goldInk;
    return AppColors.danger;
  }

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final accent = subjectAccent(subject);
    final icon = subjectIcon(subject);
    final fill = _fillColor();

    // Day 12 — Merge icon + name + score + bar into one SR node.
    return Semantics(
      container: true,
      label: '$subject: ${arabize(score.toStringAsFixed(0))} من ${arabize(maxScore.toStringAsFixed(0))}',
      excludeSemantics: true,
      child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.14),
                  shape: BoxShape.circle,
                ),
                alignment: Alignment.center,
                child: Icon(icon, size: 15, color: accent),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  subject,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: t.ink,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '${arabize(score.toStringAsFixed(0))} / ${arabize(maxScore.toStringAsFixed(0))}',
                style: TextStyle(
                  color: _scoreColor(),
                  fontWeight: FontWeight.w800,
                  fontSize: 13,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsetsDirectional.only(start: 38),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: Container(
                height: 8,
                color: t.subtleBg,
                child: Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: FractionallySizedBox(
                    widthFactor: _pct,
                    child: Container(color: fill),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    ),
    );
  }
}

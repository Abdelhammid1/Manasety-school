import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/arabize.dart';
import '../theme/colors.dart';
import '../theme/tokens.dart';

/// Circular ring showing overall attendance percentage.
///
/// Ring color reflects the rate: green ≥ 90%, gold 70-90%, red < 70%.
/// Center: big % in Arabic-Indic. Sublabel: `حاضر N / total`.
class AttendanceDonut extends StatelessWidget {
  final int present;
  final int absent;
  final int late;
  final int total;
  final double diameter;

  const AttendanceDonut({
    super.key,
    required this.present,
    required this.absent,
    required this.late,
    required this.total,
    this.diameter = 140,
  });

  double get _rate {
    if (total <= 0) return 0;
    return present / total;
  }

  Color _ringColor() {
    final p = _rate * 100;
    if (p >= 90) return AppColors.success;
    if (p >= 70) return AppColors.gold;
    return AppColors.danger;
  }

  /// Day 12 hot-fix — text color parallel to ring; gold ring uses `goldInk`
  /// (≈5:1 on white) instead of the same washed-out gold as the ring, so the
  /// hero percentage stays legible when attendance sits in the 70-90% band.
  Color _textColor() {
    final p = _rate * 100;
    if (p >= 90) return AppColors.success;
    if (p >= 70) return AppColors.goldInk;
    return AppColors.danger;
  }

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final ring = _ringColor();
    final textColor = _textColor();
    final pctText = arabize('${(_rate * 100).toStringAsFixed(0)}٪');

    // Day 12 — Combine the ring visual + the two Text children into one
    // Semantics node so TalkBack reads a complete summary instead of five
    // disconnected fragments ("85", "%", "حاضر", "68", "/", "80").
    final pctInt = (_rate * 100).round();
    return Semantics(
      container: true,
      label: 'نسبة الحضور ${arabize(pctInt)} بالمائة — حاضر ${arabize(present)} من ${arabize(total)}',
      excludeSemantics: true,
      child: SizedBox(
        width: diameter,
        height: diameter,
        child: CustomPaint(
          painter: _DonutPainter(
            progress: _rate,
            activeColor: ring,
            trackColor: t.subtleBg,
          ),
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  pctText,
                  style: TextStyle(
                    color: textColor,
                    fontSize: diameter * 0.24,
                    fontWeight: FontWeight.w900,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'حاضر ${arabize(present)} / ${arabize(total)}',
                  style: TextStyle(
                    color: t.muted,
                    fontSize: diameter * 0.09,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _DonutPainter extends CustomPainter {
  final double progress;
  final Color activeColor;
  final Color trackColor;

  _DonutPainter({
    required this.progress,
    required this.activeColor,
    required this.trackColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final strokeWidth = size.shortestSide * 0.11;
    final rect = Offset(strokeWidth / 2, strokeWidth / 2) &
        Size(size.width - strokeWidth, size.height - strokeWidth);

    final track = Paint()
      ..color = trackColor
      ..strokeWidth = strokeWidth
      ..style = PaintingStyle.stroke;
    canvas.drawArc(rect, 0, 2 * math.pi, false, track);

    if (progress > 0) {
      final active = Paint()
        ..color = activeColor
        ..strokeWidth = strokeWidth
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round;
      // Start at top (-π/2) and sweep clockwise.
      canvas.drawArc(rect, -math.pi / 2, 2 * math.pi * progress, false, active);
    }
  }

  @override
  bool shouldRepaint(covariant _DonutPainter old) =>
      old.progress != progress ||
      old.activeColor != activeColor ||
      old.trackColor != trackColor;
}

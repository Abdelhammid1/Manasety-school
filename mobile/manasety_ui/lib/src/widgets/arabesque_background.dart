import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Subtle Islamic-geometric background pattern for hero/login scaffolds.
///
/// Renders a repeating grid of 8-pointed stars (two 45°-rotated squares per
/// node), stroked at low opacity so it reads as a texture, not decoration.
/// Ideal on solid brand backgrounds (navy login scaffold, gradient hero
/// cards) where a small amount of geometric interest lifts the surface.
class ArabesqueBackground extends StatelessWidget {
  /// Stroke color for the stars. Defaults to `white @ 6%` for use on the
  /// navy login scaffold — override for other backgrounds.
  final Color? color;

  /// Approximate number of tile columns across the screen width. Higher
  /// number = denser, smaller pattern.
  final double density;

  const ArabesqueBackground({
    super.key,
    this.color,
    this.density = 3.5,
  });

  @override
  Widget build(BuildContext context) {
    // Day 12 — purely decorative; hide from TalkBack so it doesn't announce
    // the CustomPaint node when the SR user is exploring the login screen.
    return ExcludeSemantics(
      child: CustomPaint(
        size: Size.infinite,
        painter: _ArabesquePainter(
          color: color ?? Colors.white.withValues(alpha: 0.06),
          density: density,
        ),
      ),
    );
  }
}

class _ArabesquePainter extends CustomPainter {
  final Color color;
  final double density;

  _ArabesquePainter({required this.color, required this.density});

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width <= 0 || size.height <= 0) return;
    final tile = size.width / density;
    final rSquare = tile * 0.35;
    final vStep = tile * 0.87;

    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..strokeCap = StrokeCap.round;

    var row = 0;
    for (double dy = -tile; dy < size.height + tile; dy += vStep) {
      final xOffset = (row % 2 == 0) ? 0.0 : tile / 2;
      for (double dx = -tile + xOffset; dx < size.width + tile; dx += tile) {
        _drawStar(canvas, Offset(dx, dy), rSquare, paint);
      }
      row++;
    }
  }

  /// An 8-pointed star = two overlapping squares, one rotated 45°.
  void _drawStar(Canvas canvas, Offset center, double r, Paint paint) {
    for (final angle in const [0.0, math.pi / 4]) {
      canvas.save();
      canvas.translate(center.dx, center.dy);
      canvas.rotate(angle);
      canvas.drawRect(
        Rect.fromCenter(center: Offset.zero, width: r * 2, height: r * 2),
        paint,
      );
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(covariant _ArabesquePainter old) =>
      old.color != color || old.density != density;
}

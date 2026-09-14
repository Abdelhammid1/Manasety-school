import 'package:flutter/material.dart';

import '../theme/colors.dart';

/// Navy → navySoft gradient hero card with a greeting + subtitle + optional
/// trailing pill. Used at the top of every hub screen in both apps.
///
/// Renders identically on light and dark modes (brand navy stays navy for
/// recognition; text is white on both).
class GreetingCard extends StatelessWidget {
  /// Main greeting line — e.g. `"أهلاً، إيهاب"` or `"مرحبًا، ولي الأمر"`.
  final String greeting;

  /// Small subtitle underneath (typically the institution name).
  final String? subtitle;

  /// Optional trailing pill on the leading side — commonly a counter like
  /// `"3 أبناء"` or a status like `"اليوم"`.
  final Widget? trailingPill;

  final EdgeInsetsGeometry margin;

  const GreetingCard({
    super.key,
    required this.greeting,
    this.subtitle,
    this.trailingPill,
    this.margin = const EdgeInsets.fromLTRB(16, 16, 16, 0),
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: margin,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [AppColors.navy, AppColors.navySoft],
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  greeting,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                if (subtitle != null && subtitle!.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    subtitle!,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.85),
                      fontSize: 12,
                    ),
                  ),
                ],
                const SizedBox(height: 10),
                Container(
                  height: 3,
                  width: 40,
                  decoration: BoxDecoration(
                    color: AppColors.gold,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ],
            ),
          ),
          if (trailingPill != null) ...[
            const SizedBox(width: 12),
            trailingPill!,
          ],
        ],
      ),
    );
  }
}

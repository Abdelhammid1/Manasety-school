import 'package:flutter/material.dart';

import '../theme/colors.dart';

/// Section header shown above every list block on hub screens.
///
/// Small gold underline stub + Arabic label in the theme's primary color, so
/// every heading looks identical whether it's `أبناؤك`, `فصولك`, or
/// `حصصك القادمة`. Optional trailing action (e.g. "see all" chevron button).
class SectionHeading extends StatelessWidget {
  final String title;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;

  const SectionHeading({
    super.key,
    required this.title,
    this.trailing,
    this.padding = const EdgeInsets.fromLTRB(20, 18, 20, 8),
  });

  @override
  Widget build(BuildContext context) {
    final primary = Theme.of(context).colorScheme.primary;
    return Padding(
      padding: padding,
      child: Row(
        children: [
          Container(
            width: 4,
            height: 18,
            decoration: BoxDecoration(
              color: AppColors.gold,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              title,
              style: TextStyle(
                color: primary,
                fontWeight: FontWeight.w800,
                fontSize: 15,
              ),
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../theme/tokens.dart';

class EmptyState extends StatelessWidget {
  final IconData icon;

  /// Day 9 — optional custom illustration widget. When set, replaces the
  /// plain [icon]. Callers typically pass `EmptyIllustration(kind: …)` from
  /// this package, but any Widget works.
  final Widget? illustration;

  final String title;
  final String? description;
  final Widget? action;

  const EmptyState({
    super.key,
    this.icon = Icons.inbox_outlined,
    this.illustration,
    required this.title,
    this.description,
    this.action,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            illustration ?? Icon(icon, size: 56, color: t.muted),
            const SizedBox(height: 16),
            Text(
              title,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: t.ink,
                fontSize: 16,
                fontWeight: FontWeight.w700,
              ),
            ),
            if (description != null) ...[
              const SizedBox(height: 6),
              Text(
                description!,
                textAlign: TextAlign.center,
                style: TextStyle(color: t.muted, fontSize: 13),
              ),
            ],
            if (action != null) ...[const SizedBox(height: 16), action!],
          ],
        ),
      ),
    );
  }
}

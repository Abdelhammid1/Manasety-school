import 'package:flutter/material.dart';

/// Day 13 — Wraps a bare [EmptyState] so it stays refreshable.
///
/// [RefreshIndicator] / [AppRefreshIndicator] only fire when their child is
/// scrollable and reports the overscroll. A non-scrolling `EmptyState`
/// breaks that contract — pull-to-refresh doesn't work on empty lists.
///
/// Solution: hand the SingleChildScrollView (with `AlwaysScrollableScrollPhysics`)
/// a child sized to at least the viewport height, so the refresh spinner
/// engages while the empty state stays visually centered.
///
/// Usage:
/// ```dart
/// if (list.isEmpty) return const RefreshableEmpty(child: EmptyState(...));
/// ```
class RefreshableEmpty extends StatelessWidget {
  final Widget child;

  const RefreshableEmpty({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (_, constraints) => SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: child,
        ),
      ),
    );
  }
}

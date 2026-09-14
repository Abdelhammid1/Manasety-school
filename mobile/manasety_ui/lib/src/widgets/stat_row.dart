import 'package:flutter/material.dart';

import 'stat_tile.dart';

/// Horizontal row of equal-width [StatTile]s. Sits below the greeting card
/// on hub screens.
///
/// Handles horizontal padding + inter-tile gaps so callers just pass a list.
class StatRow extends StatelessWidget {
  final List<StatTile> tiles;
  final EdgeInsetsGeometry padding;

  const StatRow({
    super.key,
    required this.tiles,
    this.padding = const EdgeInsets.fromLTRB(16, 12, 16, 4),
  });

  @override
  Widget build(BuildContext context) {
    if (tiles.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: padding,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < tiles.length; i++) ...[
            Expanded(child: tiles[i]),
            if (i != tiles.length - 1) const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }
}

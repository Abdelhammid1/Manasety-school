import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../theme/tokens.dart';

/// Shimmer wrapper — every skeleton renders inside this so the shimmer sweep
/// colors adapt to light/dark mode via the theme's tokens.
class _Shimmer extends StatelessWidget {
  final Widget child;
  const _Shimmer({required this.child});
  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    return Shimmer.fromColors(
      baseColor: t.subtleBg,
      highlightColor: t.border,
      period: const Duration(milliseconds: 1400),
      child: child,
    );
  }
}

/// A single grey rounded block — the primitive.
class SkeletonBlock extends StatelessWidget {
  final double width;
  final double height;
  final double radius;
  const SkeletonBlock({
    super.key,
    this.width = double.infinity,
    this.height = 12,
    this.radius = 6,
  });
  @override
  Widget build(BuildContext context) {
    return _Shimmer(
      child: Container(
        width: width,
        height: height,
        decoration: BoxDecoration(
          color: context.tokens.subtleBg,
          borderRadius: BorderRadius.circular(radius),
        ),
      ),
    );
  }
}

/// Row of three stat-tile silhouettes — mirrors the layout of [StatRow] so
/// swap-in on data-arrival is seamless.
class SkeletonStatRow extends StatelessWidget {
  const SkeletonStatRow({super.key});
  @override
  Widget build(BuildContext context) {
    Widget tile() => Expanded(
          child: _Shimmer(
            child: Container(
              height: 72,
              decoration: BoxDecoration(
                color: context.tokens.subtleBg,
                borderRadius: BorderRadius.circular(12),
              ),
            ),
          ),
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Row(
        children: [
          tile(),
          const SizedBox(width: 8),
          tile(),
          const SizedBox(width: 8),
          tile(),
        ],
      ),
    );
  }
}

/// Accent-rail card silhouette — mirrors [AccentRailCard] with
/// [TintedIconAvatar] leading + 2 lines + a chip strip.
class SkeletonCard extends StatelessWidget {
  final bool showChips;
  const SkeletonCard({super.key, this.showChips = true});
  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    return _Shimmer(
      child: Container(
        decoration: BoxDecoration(
          color: t.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: t.border),
        ),
        child: IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(width: 4, color: t.subtleBg),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    children: [
                      Container(
                        width: 44, height: 44,
                        decoration: BoxDecoration(
                          color: t.subtleBg,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Container(width: 140, height: 14, color: t.subtleBg),
                            const SizedBox(height: 8),
                            Container(width: 100, height: 10, color: t.subtleBg),
                            if (showChips) ...[
                              const SizedBox(height: 10),
                              Row(
                                children: [
                                  Container(width: 48, height: 18, decoration: BoxDecoration(color: t.subtleBg, borderRadius: BorderRadius.circular(12))),
                                  const SizedBox(width: 6),
                                  Container(width: 48, height: 18, decoration: BoxDecoration(color: t.subtleBg, borderRadius: BorderRadius.circular(12))),
                                  const SizedBox(width: 6),
                                  Container(width: 48, height: 18, decoration: BoxDecoration(color: t.subtleBg, borderRadius: BorderRadius.circular(12))),
                                ],
                              ),
                            ],
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The full hub-screen skeleton — hero greeting placeholder + stat row +
/// N accent-rail cards. Drop-in `skeleton:` param for `AsyncValueWidget`
/// on hub screens (ChildrenScreen, SectionsScreen).
class SkeletonHub extends StatelessWidget {
  final int cardCount;
  final bool showChips;
  const SkeletonHub({super.key, this.cardCount = 3, this.showChips = true});

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    return ListView(
      physics: const NeverScrollableScrollPhysics(),
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        // Greeting-card silhouette.
        _Shimmer(
          child: Container(
            margin: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            height: 110,
            decoration: BoxDecoration(
              color: t.subtleBg,
              borderRadius: BorderRadius.circular(16),
            ),
          ),
        ),
        const SkeletonStatRow(),
        const SizedBox(height: 12),
        // Section-heading silhouette.
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 6, 20, 8),
          child: _Shimmer(
            child: Container(
              width: 90, height: 14,
              color: t.subtleBg,
            ),
          ),
        ),
        for (var i = 0; i < cardCount; i++)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: SkeletonCard(showChips: showChips),
          ),
      ],
    );
  }
}

/// N stacked accent-rail card silhouettes — for tab bodies (attendance,
/// materials, invoices) where the content is a plain list.
class SkeletonList extends StatelessWidget {
  final int itemCount;
  final bool showChips;
  const SkeletonList({super.key, this.itemCount = 5, this.showChips = false});
  @override
  Widget build(BuildContext context) {
    return ListView.separated(
      physics: const NeverScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      itemCount: itemCount,
      separatorBuilder: (_, __) => const SizedBox(height: 10),
      itemBuilder: (_, __) => SkeletonCard(showChips: showChips),
    );
  }
}

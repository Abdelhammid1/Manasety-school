import 'package:flutter/material.dart';

import '../theme/colors.dart';
import '../theme/tokens.dart';

/// Themed `RefreshIndicator` + Arabic completion feedback.
///
/// - Spinner color is navy on light, gold on dark (brand accent that reads on
///   both scaffolds).
/// - When the refresh future resolves, a floating `تم التحديث` snack appears
///   with a `حسناً` dismiss action. Suppress with `showSuccessSnack: false`
///   for chat-style screens where refresh happens frequently.
class AppRefreshIndicator extends StatelessWidget {
  final Widget child;
  final Future<void> Function() onRefresh;
  final bool showSuccessSnack;

  const AppRefreshIndicator({
    super.key,
    required this.child,
    required this.onRefresh,
    this.showSuccessSnack = true,
  });

  @override
  Widget build(BuildContext context) {
    final ring = Theme.of(context).brightness == Brightness.dark
        ? AppColors.gold
        : AppColors.navy;

    return RefreshIndicator(
      onRefresh: () async {
        await onRefresh();
        if (!context.mounted || !showSuccessSnack) return;
        final messenger = ScaffoldMessenger.of(context);
        messenger.hideCurrentSnackBar();
        messenger.showSnackBar(
          SnackBar(
            behavior: SnackBarBehavior.floating,
            duration: const Duration(seconds: 2),
            content: const Text('تم التحديث'),
            action: SnackBarAction(
              label: 'حسناً',
              textColor: AppColors.gold,
              onPressed: () => messenger.hideCurrentSnackBar(),
            ),
          ),
        );
      },
      color: ring,
      backgroundColor: context.tokens.surface,
      strokeWidth: 2.4,
      child: child,
    );
  }
}

import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../theme/tokens.dart';

class ErrorView extends StatelessWidget {
  final Object error;
  final VoidCallback? onRetry;
  final EdgeInsets padding;

  const ErrorView({
    super.key,
    required this.error,
    this.onRetry,
    this.padding = const EdgeInsets.all(24),
  });

  String _message() {
    final e = error;
    if (e is ApiException) return e.message;
    return 'حدث خطأ غير متوقّع';
  }

  IconData _icon() {
    final e = error;
    if (e is NetworkException) return Icons.wifi_off_rounded;
    if (e is UnauthorizedException) return Icons.lock_outline;
    if (e is ForbiddenException) return Icons.block;
    if (e is NotFoundException) return Icons.search_off;
    return Icons.error_outline;
  }

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    return Center(
      child: Padding(
        padding: padding,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(_icon(), size: 48, color: t.muted),
            const SizedBox(height: 12),
            Text(
              _message(),
              textAlign: TextAlign.center,
              style: TextStyle(color: t.ink, fontSize: 15),
            ),
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('إعادة المحاولة'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

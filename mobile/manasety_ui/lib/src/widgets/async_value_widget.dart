import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../theme/colors.dart';
import 'error_view.dart';

/// مغلّف عام يكشف AsyncValue ويعرض حالات التحميل/الخطأ/البيانات.
///
/// If [skeleton] is provided it is shown during the loading state
/// (typically one of `SkeletonHub` / `SkeletonList` / `SkeletonCard`).
/// If omitted, a plain themed spinner is used.
class AsyncValueWidget<T> extends StatelessWidget {
  final AsyncValue<T> value;
  final Widget Function(T data) data;
  final VoidCallback? onRetry;
  final Widget? skeleton;

  const AsyncValueWidget({
    super.key,
    required this.value,
    required this.data,
    this.onRetry,
    this.skeleton,
  });

  @override
  Widget build(BuildContext context) {
    final spinnerColor = Theme.of(context).brightness == Brightness.dark
        ? AppColors.gold
        : AppColors.navy;
    return value.when(
      data: data,
      loading: () =>
          skeleton ??
          Center(child: CircularProgressIndicator(color: spinnerColor)),
      error: (e, _) => ErrorView(error: e, onRetry: onRetry),
    );
  }
}

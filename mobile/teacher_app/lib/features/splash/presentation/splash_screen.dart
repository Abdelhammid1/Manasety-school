import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';
import '../../../core/storage/secure_storage.dart';

/// [TCH] Splash — matches the Stitch design (`design_refs/tch/splash.png`).
/// Navy background with a subtle dot pattern, top-right portal pill,
/// top-left cloud-connected status pill, centered stacked emblem,
/// "منصتي" wordmark, sync pill, animated progress bar, version footer.
class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});
  @override
  ConsumerState<SplashScreen> createState() => _S();
}

class _S extends ConsumerState<SplashScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _bar =
      AnimationController(vsync: this, duration: const Duration(seconds: 2))..forward();
  @override
  void initState() {
    super.initState();
    Timer(const Duration(milliseconds: 1600), _redirect);
  }
  Future<void> _redirect() async {
    final tok = await ref.read(secureStorageProvider).readToken();
    if (!mounted) return;
    context.go(tok != null && tok.isNotEmpty ? Routes.home : Routes.login);
  }
  @override
  void dispose() { _bar.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: DecoratedBox(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topRight, end: Alignment.bottomLeft,
          colors: [ManasetyBrand.navy, Color(0xFF12276B)],
        ),
      ),
      child: SafeArea(child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: Column(children: [
          const SizedBox(height: 8),
          Row(children: [
            _TopPill(
              icon: Icons.cloud_done_rounded,
              label: 'متصل بالسحابة الأكاديمية',
              statusDot: true,
            ),
            const Spacer(),
            _TopPill(
              icon: Icons.school_rounded,
              label: 'بوابة المنظومة',
              filled: false,
            ),
          ]),
          const Spacer(),
          const _StackedEmblem(),
          const SizedBox(height: 20),
          const Text('منصتي', style: TextStyle(
            color: Colors.white, fontSize: 34, fontWeight: FontWeight.w800,
            letterSpacing: -0.5)),
          const SizedBox(height: 6),
          const Text('نظام إدارة التعلم المدرسي الذكي',
            style: TextStyle(color: Colors.white70, fontSize: 13)),
          const SizedBox(height: 20),
          Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: Colors.white.withValues(alpha: 0.15))),
            child: const Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.auto_awesome_rounded, color: Color(0xFF0099CC), size: 14),
              SizedBox(width: 6),
              Text('مزامنة بيانات الفصول والطلاب…',
                style: TextStyle(color: Colors.white, fontSize: 12)),
            ])),
          const Spacer(),
          SizedBox(width: double.infinity, height: 4,
            child: ClipRRect(borderRadius: BorderRadius.circular(4),
              child: AnimatedBuilder(animation: _bar, builder: (_, __) => LinearProgressIndicator(
                value: _bar.value,
                backgroundColor: Colors.white.withValues(alpha: 0.15),
                valueColor: const AlwaysStoppedAnimation(Color(0xFF0099CC)),
              )))),
          const SizedBox(height: 20),
          Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.05),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: Colors.white.withValues(alpha: 0.15))),
            child: const Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.verified_user_rounded, color: Colors.white70, size: 14),
              SizedBox(width: 6),
              Text('الإصدار 1.0.0 — بوابة المعلم',
                style: TextStyle(color: Colors.white, fontSize: 12)),
            ])),
          const SizedBox(height: 8),
          const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            Icon(Icons.account_balance_rounded, color: Colors.white54, size: 12),
            SizedBox(width: 6),
            Text('منظومة التعليم العام المتطورة',
              style: TextStyle(color: Colors.white54, fontSize: 11)),
          ]),
          const SizedBox(height: 16),
        ]),
      )),
    ),
  );
}

class _TopPill extends StatelessWidget {
  const _TopPill({required this.icon, required this.label,
    this.statusDot = false, this.filled = true});
  final IconData icon; final String label;
  final bool statusDot; final bool filled;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    decoration: BoxDecoration(
      color: filled ? Colors.white.withValues(alpha: 0.10) : Colors.transparent,
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: Colors.white.withValues(alpha: 0.20)),
    ),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      if (statusDot) ...[
        Container(width: 8, height: 8,
          decoration: const BoxDecoration(color: ManasetyBrand.success, shape: BoxShape.circle)),
        const SizedBox(width: 6),
      ],
      Icon(icon, color: Colors.white, size: 14),
      const SizedBox(width: 6),
      Text(label, style: const TextStyle(color: Colors.white, fontSize: 11)),
    ]),
  );
}

class _StackedEmblem extends StatelessWidget {
  const _StackedEmblem();
  @override
  Widget build(BuildContext context) => SizedBox(width: 148, height: 148,
    child: Stack(children: [
      // frosted-glass rounded square with a book icon
      Positioned.fill(child: Container(
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(28),
          border: Border.all(color: Colors.white.withValues(alpha: 0.15)),
        ),
        child: const Icon(Icons.menu_book_rounded, color: Colors.white, size: 68),
      )),
      // overlapping cyan-blue circle with graduation cap
      Positioned(left: 10, bottom: 10, child: Container(width: 48, height: 48,
        decoration: BoxDecoration(
          gradient: const LinearGradient(colors: [Color(0xFF2563EB), Color(0xFF0099CC)]),
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white.withValues(alpha: 0.15), width: 2),
        ),
        child: const Icon(Icons.school_rounded, color: Colors.white, size: 26))),
    ]),
  );
}

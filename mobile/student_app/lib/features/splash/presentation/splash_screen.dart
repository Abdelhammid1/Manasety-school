import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';
import '../../../core/storage/secure_storage.dart';
import '../../../shared/brand/manasety_wordmark.dart';

/// Full-bleed brand gradient splash — mirrors [STU] Splash from the
/// Stitch export. Decides whether to go to /login or /home based on the
/// presence of a saved auth token.
class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _bar =
      AnimationController(vsync: this, duration: const Duration(seconds: 2))
        ..forward();

  @override
  void initState() {
    super.initState();
    Timer(const Duration(milliseconds: 1400), _redirect);
  }

  Future<void> _redirect() async {
    final storage = ref.read(secureStorageProvider);
    final token = await storage.readToken();
    if (!mounted) return;
    context.go(token != null && token.isNotEmpty ? Routes.home : Routes.login);
  }

  @override
  void dispose() {
    _bar.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(gradient: ManasetyBrand.primaryGradient),
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Official Manasety wordmark (same SVG the web ships).
              const ManasetyWordmark(height: 80, color: Colors.white),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
                ),
                child: const Text(
                  'K-12',
                  style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600),
                ),
              ),
              const SizedBox(height: 32),
              SizedBox(
                width: 200,
                height: 3,
                child: AnimatedBuilder(
                  animation: _bar,
                  builder: (_, __) => LinearProgressIndicator(
                    value: _bar.value,
                    backgroundColor: Colors.white.withValues(alpha: 0.2),
                    valueColor: const AlwaysStoppedAnimation(Colors.white),
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

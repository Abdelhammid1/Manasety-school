import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';

/// Day 13 (v3) — Flutter-side welcome splash.
///
/// The native OS splash (color + centered medallion) shows for the sub-second
/// between tap-to-launch and Flutter's first frame. This screen then paints
/// the full illuminated-manuscript design edge-to-edge for ~1.4 s, and
/// finally navigates to [Routes.home] (which the router redirects to
/// [Routes.login] or the children hub based on auth state).
///
/// This is the SAME image the OS splash would show if Android's splash API
/// allowed full-bleed backgrounds — but on Android 12+ it doesn't, so we
/// paint it in Flutter for uniform behavior across every device.
class WelcomeSplashScreen extends StatefulWidget {
  const WelcomeSplashScreen({super.key});

  @override
  State<WelcomeSplashScreen> createState() => _WelcomeSplashScreenState();
}

class _WelcomeSplashScreenState extends State<WelcomeSplashScreen> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer(const Duration(milliseconds: 1400), () {
      if (!mounted) return;
      // Hand off to the router — its redirect callback picks the right
      // destination based on current auth state.
      context.go(Routes.home);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.navy,
      body: SizedBox.expand(
        child: Image(
          image: AssetImage('assets/images/splash-bg.png'),
          fit: BoxFit.cover,
          alignment: Alignment.center,
          gaplessPlayback: true,
        ),
      ),
    );
  }
}

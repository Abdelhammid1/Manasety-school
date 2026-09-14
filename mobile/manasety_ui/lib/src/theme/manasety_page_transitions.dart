import 'package:flutter/material.dart';

/// App-wide page transition — subtle slide from the leading edge + short fade
/// over 280 ms (from the route's default duration).
///
/// The direction is RTL-aware: in the Arabic apps the new page slides in from
/// the LEFT (visual leading edge in RTL), reversing on pop. Falls back to a
/// right-origin slide in LTR contexts.
class ManasetyPageTransitionsBuilder extends PageTransitionsBuilder {
  const ManasetyPageTransitionsBuilder();

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) {
    final rtl = Directionality.of(context) == TextDirection.rtl;
    final beginOffset = rtl ? const Offset(-0.08, 0) : const Offset(0.08, 0);

    final slide = Tween<Offset>(
      begin: beginOffset,
      end: Offset.zero,
    ).animate(
      CurvedAnimation(parent: animation, curve: Curves.fastOutSlowIn),
    );

    return SlideTransition(
      position: slide,
      child: FadeTransition(opacity: animation, child: child),
    );
  }
}

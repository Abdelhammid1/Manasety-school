import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// Renders the official Manasety "منصتي" wordmark from `assets/brand/
/// manasety-wordmark.svg` — this is the SAME file the web app ships as
/// `static/img/logo.svg`, so brand consistency is guaranteed.
///
/// The SVG is authored with the navy → blue → cyan gradient baked in.
/// Pass [color] to tint everything a solid colour (e.g. white on the
/// splash gradient).
class ManasetyWordmark extends StatelessWidget {
  const ManasetyWordmark({
    super.key,
    this.height = 64,
    this.color,
  });

  final double height;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return SvgPicture.asset(
      'assets/brand/manasety-wordmark.svg',
      height: height,
      colorFilter: color == null
          ? null
          : ColorFilter.mode(color!, BlendMode.srcIn),
      semanticsLabel: 'شعار منصتي',
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// Renders the official Manasety wordmark (same SVG the web ships).
class ManasetyWordmark extends StatelessWidget {
  const ManasetyWordmark({super.key, this.height = 64, this.color});
  final double height;
  final Color? color;
  @override
  Widget build(BuildContext context) => SvgPicture.asset(
    'assets/brand/manasety-wordmark.svg',
    height: height,
    colorFilter: color == null ? null : ColorFilter.mode(color!, BlendMode.srcIn),
    semanticsLabel: 'شعار منصتي',
  );
}

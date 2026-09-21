import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';
class AnnouncementsScreen extends StatelessWidget {
  const AnnouncementsScreen({super.key});
  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: ManasetyBrand.surface,
    appBar: AppBar(title: const Text('إعلاناتي')),
    body: const Center(child: Text('قيد التطوير',
      style: TextStyle(color: ManasetyBrand.onSurfaceVariant))),
  );
}

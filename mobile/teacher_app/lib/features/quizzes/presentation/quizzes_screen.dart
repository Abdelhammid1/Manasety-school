import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';
class QuizzesScreen extends StatelessWidget {
  const QuizzesScreen({super.key});
  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: ManasetyBrand.surface,
    appBar: AppBar(title: const Text('اختباراتي')),
    body: const Center(child: Text('قيد التطوير',
      style: TextStyle(color: ManasetyBrand.onSurfaceVariant))),
  );
}

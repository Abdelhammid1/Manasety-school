import 'package:flutter/material.dart';
import 'package:manasety_ui/manasety_ui.dart';
class MessagesScreen extends StatelessWidget {
  const MessagesScreen({super.key});
  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: ManasetyBrand.surface,
    appBar: AppBar(title: const Text('الرسائل')),
    body: const Center(child: Text('قيد التطوير',
      style: TextStyle(color: ManasetyBrand.onSurfaceVariant))),
  );
}

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/dio_client.dart';
import '../../core/api/endpoints.dart';

/// Banner that surfaces active PickupCall records where the current
/// user is the responsible teacher. Polls every 15 s and disappears
/// when no calls are active. Wrap your home Scaffold's body with a
/// Column containing this widget on top.
class PickupBanner extends ConsumerStatefulWidget {
  const PickupBanner({super.key});
  @override
  ConsumerState<PickupBanner> createState() => _PickupBannerState();
}

class _PickupBannerState extends ConsumerState<PickupBanner> {
  List<Map<String, dynamic>> _calls = const [];
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Dio get _dio => ref.read(dioProvider);

  Future<void> _refresh() async {
    try {
      final res = await _dio.get(Endpoints.pickupIncoming);
      final list = (res.data['calls'] as List? ?? const []);
      if (mounted) {
        setState(() =>
            _calls = list.map((e) => Map<String, dynamic>.from(e as Map)).toList());
      }
    } catch (_) {}
  }

  Future<void> _ack(int id) async {
    try {
      await _dio.post(Endpoints.pickupAck(id));
    } catch (_) {}
    await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    if (_calls.isEmpty) return const SizedBox.shrink();
    return Column(
      children: [
        for (final c in _calls)
          Container(
            margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(20),
              gradient: const LinearGradient(
                  colors: [Color(0xFF059669), Color(0xFF10B981)]),
              boxShadow: const [
                BoxShadow(
                    color: Color(0x33059669), blurRadius: 20, offset: Offset(0, 8))
              ],
            ),
            padding: const EdgeInsets.all(14),
            child: Row(children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Icon(Icons.notifications_active,
                    color: Colors.white, size: 26),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('نداء ولي أمر',
                        style: TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 16)),
                    Text(
                      '${c['parent_name']} في انتظار ${c['student_name']} — ${c['gate'] ?? 'خارج المدرسة'} · منذ ${c['waited_min']} دقيقة',
                      style: const TextStyle(color: Colors.white70, fontSize: 13),
                    ),
                  ],
                ),
              ),
              TextButton(
                onPressed: () => _ack(c['id'] as int),
                style: TextButton.styleFrom(
                    foregroundColor: Colors.white,
                    backgroundColor: Colors.white.withValues(alpha: 0.2)),
                child: const Text('تم'),
              ),
            ]),
          ),
      ],
    );
  }
}

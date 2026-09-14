import 'dart:convert';

class NotificationItem {
  final int id;
  final String kind;
  final String status;
  final Map<String, dynamic> payload;
  final DateTime createdAt;

  const NotificationItem({
    required this.id,
    required this.kind,
    required this.status,
    required this.payload,
    required this.createdAt,
  });

  factory NotificationItem.fromJson(Map<String, dynamic> j) {
    Map<String, dynamic> payload = const {};
    final raw = j['payload'];
    if (raw is String && raw.isNotEmpty) {
      try {
        final decoded = jsonDecode(raw);
        if (decoded is Map<String, dynamic>) payload = decoded;
      } catch (_) {/* ignore malformed payload */}
    } else if (raw is Map<String, dynamic>) {
      payload = raw;
    }
    return NotificationItem(
      id: j['id'] as int,
      kind: (j['kind'] ?? '') as String,
      status: (j['status'] ?? '') as String,
      payload: payload,
      createdAt:
          DateTime.tryParse((j['created_at'] ?? '') as String) ?? DateTime.now(),
    );
  }

  /// Renders a human-friendly Arabic message from the payload + kind.
  String get displayMessage {
    final msg = payload['message'];
    if (msg is String && msg.isNotEmpty) return msg;
    final student = payload['student'] as String?;
    final date = payload['date'] as String?;
    switch (kind) {
      case 'absence':
        return 'تم تسجيل غياب${student != null ? " لـ $student" : ""}${date != null ? " بتاريخ $date" : ""}';
      case 'result_approved':
        return 'تم اعتماد نتائج ${student ?? "ابنك"}';
      case 'invoice_issued':
        return 'تم إصدار فاتورة جديدة';
      case 'payment_received':
        return 'تم استلام دفعة';
      default:
        return 'إشعار جديد';
    }
  }
}

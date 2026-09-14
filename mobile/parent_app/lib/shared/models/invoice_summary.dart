class InvoiceSummary {
  final int id;
  final String number;
  final DateTime issueDate;
  final DateTime dueDate;
  final double totalAmount;
  final double paidAmount;
  final double remaining;
  final String status; // pending/partial/paid/overdue

  const InvoiceSummary({
    required this.id,
    required this.number,
    required this.issueDate,
    required this.dueDate,
    required this.totalAmount,
    required this.paidAmount,
    required this.remaining,
    required this.status,
  });

  factory InvoiceSummary.fromJson(Map<String, dynamic> j) => InvoiceSummary(
        id: j['id'] as int,
        number: (j['number'] ?? '') as String,
        issueDate: DateTime.parse(j['issue_date'] as String),
        dueDate: DateTime.parse(j['due_date'] as String),
        totalAmount: ((j['total_amount'] ?? 0) as num).toDouble(),
        paidAmount: ((j['paid_amount'] ?? 0) as num).toDouble(),
        remaining: ((j['remaining'] ?? 0) as num).toDouble(),
        status: (j['status'] ?? 'pending') as String,
      );

  String get statusAr {
    switch (status) {
      case 'paid':
        return 'مدفوعة';
      case 'partial':
        return 'مدفوعة جزئيًا';
      case 'overdue':
        return 'متأخّرة';
      case 'pending':
        return 'معلّقة';
      default:
        return status;
    }
  }
}

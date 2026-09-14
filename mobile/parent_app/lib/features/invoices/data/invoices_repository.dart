import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/invoice_summary.dart';

final invoicesRepositoryProvider = Provider<InvoicesRepository>((ref) {
  return InvoicesRepository(ref.watch(dioProvider));
});

class InvoicesRepository {
  final Dio _dio;
  InvoicesRepository(this._dio);

  Future<List<InvoiceSummary>> forChild(int studentId) async {
    try {
      final r = await _dio.get(Endpoints.parentChildInvoices(studentId));
      final raw = (r.data['invoices'] as List?) ?? const [];
      return raw
          .map((e) => InvoiceSummary.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }
}

final childInvoicesProvider =
    FutureProvider.autoDispose.family<List<InvoiceSummary>, int>((ref, id) {
  return ref.watch(invoicesRepositoryProvider).forChild(id);
});

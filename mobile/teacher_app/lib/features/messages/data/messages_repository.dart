import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class ConversationSummary {
  final int id;
  final String? subject, otherName, otherRole, contextType, lastPreview,
    createdAt, lastMessageAt, status;
  final int? contextId, unreadCount;
  const ConversationSummary({
    required this.id, this.subject, this.otherName, this.otherRole,
    this.contextType, this.contextId, this.lastPreview,
    this.createdAt, this.lastMessageAt, this.status, this.unreadCount,
  });
  factory ConversationSummary.fromJson(Map<String, dynamic> j) => ConversationSummary(
    id: (j['id'] as num).toInt(),
    subject: j['subject'] as String?,
    otherName: j['other_name'] as String?,
    otherRole: j['other_role'] as String?,
    contextType: j['context_type'] as String?,
    contextId: (j['context_id'] as num?)?.toInt(),
    lastPreview: j['last_preview'] as String?,
    createdAt: j['created_at'] as String?,
    lastMessageAt: j['last_message_at'] as String?,
    status: j['status'] as String?,
    unreadCount: (j['unread_count'] as num?)?.toInt(),
  );
}

class MessageItem {
  final int id;
  final String body;
  final int senderUserId;
  final String? senderName, createdAt;
  final bool isMine;
  const MessageItem({
    required this.id, required this.body, required this.senderUserId,
    this.senderName, this.createdAt, this.isMine = false,
  });
  factory MessageItem.fromJson(Map<String, dynamic> j) => MessageItem(
    id: (j['id'] as num).toInt(),
    body: j['body'] as String? ?? '',
    senderUserId: (j['sender_user_id'] as num).toInt(),
    senderName: j['sender_name'] as String?,
    createdAt: j['created_at'] as String?,
    isMine: j['is_mine'] as bool? ?? false,
  );
}

class MessagesRepository {
  MessagesRepository(this._dio);
  final Dio _dio;
  Future<List<ConversationSummary>> inbox() async {
    final r = await _dio.get(Endpoints.messages);
    return ((r.data as Map)['conversations'] as List)
      .map((e) => ConversationSummary.fromJson((e as Map).cast<String, dynamic>())).toList();
  }
  Future<(ConversationSummary, List<MessageItem>)> thread(int id) async {
    final r = await _dio.get(Endpoints.messageThread(id));
    final data = (r.data as Map).cast<String, dynamic>();
    final conv = ConversationSummary.fromJson(
      (data['conversation'] as Map).cast<String, dynamic>());
    final msgs = (data['messages'] as List)
      .map((e) => MessageItem.fromJson((e as Map).cast<String, dynamic>())).toList();
    return (conv, msgs);
  }
  Future<MessageItem> reply(int convId, String body) async {
    final r = await _dio.post(Endpoints.messageThread(convId), data: {'body': body});
    return MessageItem.fromJson(
      ((r.data as Map)['message'] as Map).cast<String, dynamic>());
  }
}

final messagesRepositoryProvider = Provider<MessagesRepository>((ref) =>
    MessagesRepository(ref.watch(dioProvider)));

final inboxProvider = FutureProvider.autoDispose<List<ConversationSummary>>((ref) =>
    ref.watch(messagesRepositoryProvider).inbox());

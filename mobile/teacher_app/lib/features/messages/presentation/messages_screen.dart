import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/messages_repository.dart';

/// [TCH] Tch Messages — matches `design_refs/tch/messages_inbox.png`.
class MessagesScreen extends ConsumerStatefulWidget {
  const MessagesScreen({super.key});
  @override
  ConsumerState<MessagesScreen> createState() => _S();
}

class _S extends ConsumerState<MessagesScreen> {
  String _q = '';
  int _filter = 0; // 0=الكل, 1=أولياء الأمور, 2=الطلاب, 3=الإدارة, 4=غير مقروء
  @override
  Widget build(BuildContext context) {
    final async = ref.watch(inboxProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      body: SafeArea(child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(
          e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (items) {
          final filtered = _apply(items);
          final unread = items.where((c) => (c.unreadCount ?? 0) > 0).length;
          return Column(children: [
            _TopBar(unread: unread),
            _SearchRow(onQ: (q) => setState(() => _q = q)),
            const SizedBox(height: 8),
            _FilterPills(active: _filter,
              onTap: (i) => setState(() => _filter = i),
              unreadCount: unread),
            const SizedBox(height: 8),
            Expanded(child: RefreshIndicator(
              onRefresh: () async {
                ref.invalidate(inboxProvider);
                await ref.read(inboxProvider.future);
              },
              child: filtered.isEmpty
                ? const _EmptyView()
                : ListView.builder(padding: const EdgeInsets.symmetric(horizontal: 16),
                  itemCount: filtered.length,
                  itemBuilder: (_, i) => Padding(padding: const EdgeInsets.only(bottom: 8),
                    child: _ConversationRow(item: filtered[i],
                      onTap: () => Navigator.push(context, MaterialPageRoute(
                        builder: (_) => _ThreadScreen(convId: filtered[i].id))))))),
            ),
          ]);
        },
      )),
    );
  }
  List<ConversationSummary> _apply(List<ConversationSummary> all) {
    var r = all;
    if (_filter == 1) r = r.where((c) => c.otherRole == 'ولي أمر').toList();
    else if (_filter == 2) r = r.where((c) => c.contextType == 'student' || (c.otherRole == null)).toList();
    else if (_filter == 4) r = r.where((c) => (c.unreadCount ?? 0) > 0).toList();
    if (_q.trim().isNotEmpty) {
      r = r.where((c) =>
        (c.otherName ?? '').contains(_q) ||
        (c.subject ?? '').contains(_q) ||
        (c.lastPreview ?? '').contains(_q)).toList();
    }
    return r;
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.unread});
  final int unread;
  @override
  Widget build(BuildContext context) => Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
    child: Row(children: [
      Container(width: 40, height: 40,
        decoration: BoxDecoration(color: ManasetyBrand.navy,
          borderRadius: BorderRadius.circular(12)),
        child: const Icon(Icons.person_rounded, color: Colors.white, size: 20)),
      const SizedBox(width: 10),
      const Icon(Icons.more_vert_rounded, color: ManasetyBrand.onSurface),
      const Spacer(),
      const Text('Tch Messages',
        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
      const SizedBox(width: 8),
      InkWell(onTap: () => Navigator.of(context).maybePop(),
        child: const Icon(Icons.arrow_forward_rounded, color: ManasetyBrand.onSurface)),
    ]));
}

class _SearchRow extends StatelessWidget {
  const _SearchRow({required this.onQ});
  final ValueChanged<String> onQ;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 16),
    child: Row(children: [
      Container(width: 44, height: 44,
        decoration: BoxDecoration(color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE2E8F0))),
        child: const Icon(Icons.tune_rounded, size: 20, color: ManasetyBrand.onSurface)),
      const SizedBox(width: 10),
      Expanded(child: TextField(onChanged: onQ,
        decoration: InputDecoration(
          filled: true, fillColor: Colors.white,
          hintText: 'ابحث عن ولي أمر أو طالب…',
          hintStyle: const TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 12),
          prefixIcon: const Icon(Icons.search_rounded, size: 20, color: ManasetyBrand.onSurfaceVariant),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: Color(0xFFE2E8F0))),
          enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: Color(0xFFE2E8F0))),
          focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: ManasetyBrand.blue)),
          contentPadding: const EdgeInsets.symmetric(vertical: 12)))),
    ]));
}

class _FilterPills extends StatelessWidget {
  const _FilterPills({required this.active, required this.onTap, required this.unreadCount});
  final int active; final ValueChanged<int> onTap; final int unreadCount;
  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    scrollDirection: Axis.horizontal,
    padding: const EdgeInsets.symmetric(horizontal: 16),
    child: Row(children: [
      _pill(0, 'الكل'),
      const SizedBox(width: 8),
      _pill(1, 'أولياء الأمور'),
      const SizedBox(width: 8),
      _pill(2, 'الطلاب'),
      const SizedBox(width: 8),
      _pill(3, 'الإدارة'),
      const SizedBox(width: 8),
      _pill(4, 'غير مقروء${unreadCount > 0 ? " ($unreadCount)" : ""}'),
    ]));
  Widget _pill(int idx, String label) {
    final selected = idx == active;
    return InkWell(onTap: () => onTap(idx),
      borderRadius: BorderRadius.circular(999),
      child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? ManasetyBrand.navy : Colors.white,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: selected ? ManasetyBrand.navy : const Color(0xFFE2E8F0))),
        child: Text(label, style: TextStyle(fontSize: 11,
          fontWeight: FontWeight.w700,
          color: selected ? Colors.white : ManasetyBrand.onSurface))));
  }
}

class _ConversationRow extends StatelessWidget {
  const _ConversationRow({required this.item, required this.onTap});
  final ConversationSummary item; final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final unread = (item.unreadCount ?? 0) > 0;
    return Material(color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(borderRadius: BorderRadius.circular(14), onTap: onTap,
        child: Container(padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFFE2E8F0))),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (unread) Container(width: 24, height: 24,
              decoration: const BoxDecoration(color: Color(0xFF10B981), shape: BoxShape.circle),
              alignment: Alignment.center,
              child: Text('${item.unreadCount}',
                style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w800)))
            else const Icon(Icons.done_all_rounded, size: 14, color: ManasetyBrand.onSurfaceVariant),
            const SizedBox(width: 8),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Row(mainAxisSize: MainAxisSize.min, children: [
                Text(_relTime(item.lastMessageAt ?? item.createdAt),
                  style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
                const Spacer(),
                Text(item.otherName ?? 'محادثة',
                  style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface),
                  maxLines: 1, overflow: TextOverflow.ellipsis),
              ]),
              if (item.subject != null && item.subject!.isNotEmpty) Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(item.subject!,
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.blue))),
              if (item.lastPreview != null && item.lastPreview!.isNotEmpty) Padding(
                padding: const EdgeInsets.only(top: 3),
                child: Text(item.lastPreview!,
                  style: TextStyle(fontSize: 11,
                    color: unread ? ManasetyBrand.onSurface : ManasetyBrand.onSurfaceVariant,
                    fontWeight: unread ? FontWeight.w600 : FontWeight.w400),
                  maxLines: 2, overflow: TextOverflow.ellipsis)),
            ])),
            const SizedBox(width: 10),
            CircleAvatar(radius: 22, backgroundColor: const Color(0xFFF1F5F9),
              child: Text(item.otherName?.characters.firstOrNull ?? 'م',
                style: const TextStyle(color: ManasetyBrand.navy, fontWeight: FontWeight.w800))),
          ]))));
  }
}

String _relTime(String? iso) {
  if (iso == null) return '';
  final t = DateTime.tryParse(iso);
  if (t == null) return '';
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 60) return 'منذ ${d.inMinutes} د';
  if (d.inHours < 24) return '${t.hour.toString().padLeft(2, "0")}:${t.minute.toString().padLeft(2, "0")}';
  if (d.inDays < 7) return 'منذ ${d.inDays}ي';
  return iso.split('T').first;
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();
  @override
  Widget build(BuildContext context) => ListView(children: [
    const SizedBox(height: 80),
    Container(padding: const EdgeInsets.all(32),
      margin: const EdgeInsets.symmetric(horizontal: 40),
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: const Column(children: [
        Icon(Icons.chat_bubble_outline_rounded, size: 48, color: ManasetyBrand.outline),
        SizedBox(height: 8),
        Text('لا رسائل بعد',
          style: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 13, fontWeight: FontWeight.w700)),
        SizedBox(height: 4),
        Text('عندما يُراسلك ولي أمر أو الإدارة ستظهر المحادثة هنا.',
          textAlign: TextAlign.center,
          style: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 11)),
      ])),
  ]);
}

/// Individual conversation thread — matches `design_refs/tch/message_thread.png`.
class _ThreadScreen extends ConsumerStatefulWidget {
  const _ThreadScreen({required this.convId});
  final int convId;
  @override
  ConsumerState<_ThreadScreen> createState() => _ThreadState();
}

class _ThreadState extends ConsumerState<_ThreadScreen> {
  late Future<(ConversationSummary, List<MessageItem>)> _future;
  final _input = TextEditingController();
  bool _sending = false;
  @override
  void initState() {
    super.initState();
    _future = ref.read(messagesRepositoryProvider).thread(widget.convId);
  }
  Future<void> _refresh() async {
    setState(() {
      _future = ref.read(messagesRepositoryProvider).thread(widget.convId);
    });
  }
  Future<void> _send() async {
    final body = _input.text.trim();
    if (body.isEmpty) return;
    setState(() => _sending = true);
    try {
      await ref.read(messagesRepositoryProvider).reply(widget.convId, body);
      _input.clear();
      await _refresh();
      ref.invalidate(inboxProvider);
    } catch (_) {} finally {
      if (mounted) setState(() => _sending = false);
    }
  }
  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: const Color(0xFFF3F6FB),
    body: SafeArea(child: FutureBuilder(future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return Center(child: Text(snap.error is ApiException
            ? (snap.error as ApiException).message : 'تعذّر التحميل'));
        }
        final (conv, msgs) = snap.data!;
        return Column(children: [
          _ThreadTopBar(),
          _ContextChip(conv: conv),
          Expanded(child: ListView(padding: const EdgeInsets.all(16),
            reverse: false,
            children: [
              _DateBadge(iso: conv.createdAt),
              const SizedBox(height: 8),
              for (final m in msgs) Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: _MessageBubble(m: m)),
            ])),
          _QuickActions(),
          _Composer(controller: _input, sending: _sending, onSend: _send),
        ]);
      })),
  );
}

class _ThreadTopBar extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
    child: Row(children: [
      Container(width: 40, height: 40,
        decoration: BoxDecoration(color: ManasetyBrand.navy,
          borderRadius: BorderRadius.circular(12)),
        child: const Icon(Icons.person_rounded, color: Colors.white, size: 20)),
      const SizedBox(width: 10),
      const Icon(Icons.more_vert_rounded, color: ManasetyBrand.onSurface),
      const Spacer(),
      const Text('Tch Message Thread',
        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
      const SizedBox(width: 8),
      InkWell(onTap: () => Navigator.of(context).maybePop(),
        child: const Icon(Icons.arrow_forward_rounded, color: ManasetyBrand.onSurface)),
    ]));
}

class _ContextChip extends StatelessWidget {
  const _ContextChip({required this.conv});
  final ConversationSummary conv;
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
          borderRadius: BorderRadius.circular(999)),
        child: const Row(mainAxisSize: MainAxisSize.min, children: [
          Text('الملف', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: ManasetyBrand.navy)),
          SizedBox(width: 4),
          Icon(Icons.chevron_left_rounded, size: 12, color: ManasetyBrand.navy),
        ])),
      const Spacer(),
      Text([
        if (conv.subject != null && conv.subject!.isNotEmpty) conv.subject!,
        if (conv.otherName != null) 'عن: ${conv.otherName}',
      ].join(' · '),
        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
      const SizedBox(width: 8),
      const Icon(Icons.school_rounded, size: 16, color: ManasetyBrand.navy),
    ]));
}

class _DateBadge extends StatelessWidget {
  const _DateBadge({required this.iso});
  final String? iso;
  @override
  Widget build(BuildContext context) => Center(child: Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      const Icon(Icons.calendar_today_rounded, size: 12, color: ManasetyBrand.onSurfaceVariant),
      const SizedBox(width: 6),
      Text(iso == null ? 'اليوم' : (iso!.split('T').first),
        style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant, fontWeight: FontWeight.w700)),
    ])));
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.m});
  final MessageItem m;
  @override
  Widget build(BuildContext context) {
    final mine = m.isMine;
    return Row(mainAxisAlignment: mine ? MainAxisAlignment.start : MainAxisAlignment.end,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (mine) _avatar(m),
        if (mine) const SizedBox(width: 8),
        Flexible(child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            gradient: mine ? ManasetyBrand.primaryGradient : null,
            color: mine ? null : Colors.white,
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(14),
              topRight: const Radius.circular(14),
              bottomLeft: Radius.circular(mine ? 14 : 2),
              bottomRight: Radius.circular(mine ? 2 : 14)),
            border: mine ? null : Border.all(color: const Color(0xFFE2E8F0))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(m.body,
              style: TextStyle(fontSize: 13,
                color: mine ? Colors.white : ManasetyBrand.onSurface,
                height: 1.5)),
            const SizedBox(height: 4),
            Row(mainAxisSize: MainAxisSize.min, children: [
              if (mine) const Icon(Icons.done_all_rounded, size: 12, color: Colors.white70),
              if (mine) const SizedBox(width: 4),
              if (mine) const Text('مقروءة',
                style: TextStyle(fontSize: 9, color: Colors.white70)),
              if (mine) const SizedBox(width: 6),
              Text(_shortTime(m.createdAt),
                style: TextStyle(fontSize: 9,
                  color: mine ? Colors.white70 : ManasetyBrand.onSurfaceVariant)),
            ]),
          ]))),
        if (!mine) const SizedBox(width: 8),
        if (!mine) _avatar(m),
      ]);
  }
  Widget _avatar(MessageItem m) => CircleAvatar(radius: 16,
    backgroundColor: const Color(0xFFF1F5F9),
    child: Text(m.senderName?.characters.firstOrNull ?? 'م',
      style: const TextStyle(color: ManasetyBrand.navy, fontSize: 12, fontWeight: FontWeight.w800)));
}

String _shortTime(String? iso) {
  if (iso == null) return '';
  final t = DateTime.tryParse(iso);
  if (t == null) return '';
  return '${t.hour.toString().padLeft(2, "0")}:${t.minute.toString().padLeft(2, "0")} ص';
}

class _QuickActions extends StatelessWidget {
  @override
  Widget build(BuildContext context) => SingleChildScrollView(scrollDirection: Axis.horizontal,
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
    child: Row(children: [
      _chip(Icons.calendar_month_rounded, 'تحديد موعد مكالمة'),
      const SizedBox(width: 8),
      _chip(Icons.assignment_turned_in_rounded, 'إرسال تقرير الواجبات'),
      const SizedBox(width: 8),
      _chip(Icons.star_border_rounded, 'سجل الدرجات'),
    ]));
  Widget _chip(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 14, color: ManasetyBrand.navy),
      const SizedBox(width: 6),
      Text(label, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
    ]));
}

class _Composer extends StatelessWidget {
  const _Composer({required this.controller, required this.sending, required this.onSend});
  final TextEditingController controller;
  final bool sending; final VoidCallback onSend;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
    decoration: const BoxDecoration(color: Colors.white,
      border: Border(top: BorderSide(color: Color(0xFFE2E8F0)))),
    child: Row(children: [
      Material(color: ManasetyBrand.blue,
        borderRadius: BorderRadius.circular(999),
        child: InkWell(borderRadius: BorderRadius.circular(999),
          onTap: sending ? null : onSend,
          child: Container(width: 44, height: 44,
            alignment: Alignment.center,
            child: sending
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.send_rounded, color: Colors.white, size: 20)))),
      const SizedBox(width: 8),
      IconButton(onPressed: () {},
        icon: const Icon(Icons.mic_rounded, color: ManasetyBrand.onSurfaceVariant)),
      Expanded(child: TextField(controller: controller,
        maxLines: 3, minLines: 1,
        textInputAction: TextInputAction.send,
        onSubmitted: (_) => onSend(),
        decoration: const InputDecoration(
          hintText: 'اكتب رسالتك هنا…',
          hintStyle: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 13),
          border: InputBorder.none))),
      const SizedBox(width: 8),
      IconButton(onPressed: () {},
        icon: const Icon(Icons.attach_file_rounded, color: ManasetyBrand.onSurfaceVariant)),
    ]));
}

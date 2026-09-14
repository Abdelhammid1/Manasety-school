import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../auth/application/auth_controller.dart';

/// Sprint 11 — Self-service profile edits.
///
/// Two independent forms sharing a scaffold:
///  1. Full name — display-only, no password required.
///  2. Username — requires current password (defense-in-depth) + a Latin-only
///     3-32 char pattern that matches the backend regex.
class EditProfileScreen extends ConsumerStatefulWidget {
  const EditProfileScreen({super.key});

  @override
  ConsumerState<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends ConsumerState<EditProfileScreen> {
  final _fullNameCtrl = TextEditingController();
  final _newUsernameCtrl = TextEditingController();
  final _currentPasswordCtrl = TextEditingController();

  bool _busyName = false;
  bool _busyUsername = false;
  String? _nameErr;
  String? _usernameErr;
  bool _hidePassword = true;

  @override
  void initState() {
    super.initState();
    final auth = ref.read(authControllerProvider);
    if (auth is Authenticated) {
      _fullNameCtrl.text = auth.user.fullName;
      _newUsernameCtrl.text = auth.user.username;
    }
  }

  @override
  void dispose() {
    _fullNameCtrl.dispose();
    _newUsernameCtrl.dispose();
    _currentPasswordCtrl.dispose();
    super.dispose();
  }

  Future<void> _submitName() async {
    setState(() {
      _busyName = true;
      _nameErr = null;
    });
    try {
      final dio = ref.read(dioProvider);
      await dio.post(Endpoints.changeFullName,
          data: {'full_name': _fullNameCtrl.text.trim()});
      await ref.read(authControllerProvider.notifier).refreshUser();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تمّ تحديث الاسم بنجاح ✓'),
          backgroundColor: AppColors.success,
        ),
      );
    } on ApiException catch (e) {
      setState(() => _nameErr = e.message);
    } catch (_) {
      setState(() => _nameErr = 'شيء ما لم يعمل — حاول مرة أخرى');
    } finally {
      if (mounted) setState(() => _busyName = false);
    }
  }

  Future<void> _submitUsername() async {
    setState(() {
      _busyUsername = true;
      _usernameErr = null;
    });
    try {
      final dio = ref.read(dioProvider);
      await dio.post(Endpoints.changeUsername, data: {
        'current_password': _currentPasswordCtrl.text,
        'new_username': _newUsernameCtrl.text.trim(),
      });
      await ref.read(authControllerProvider.notifier).refreshUser();
      if (!mounted) return;
      _currentPasswordCtrl.clear();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تمّ تحديث اسم المستخدم — استخدمه في المرة القادمة ✓'),
          backgroundColor: AppColors.success,
        ),
      );
    } on ApiException catch (e) {
      setState(() => _usernameErr = e.message);
    } catch (_) {
      setState(() => _usernameErr = 'شيء ما لم يعمل — حاول مرة أخرى');
    } finally {
      if (mounted) setState(() => _busyUsername = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authControllerProvider);
    final currentUsername = auth is Authenticated ? auth.user.username : '';

    return Scaffold(
      appBar: AppBar(title: const Text('تعديل الحساب')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ── الاسم الكامل ────────────────────────────────
            _sectionCard(
              context,
              title: 'الاسم الكامل',
              subtitle:
                  'الاسم اللي يظهر لك داخل التطبيق. يمكن تحديثه في أي وقت.',
              children: [
                TextField(
                  controller: _fullNameCtrl,
                  textInputAction: TextInputAction.done,
                  decoration: const InputDecoration(
                    labelText: 'الاسم الكامل',
                    prefixIcon: Icon(Icons.person_outline),
                  ),
                ),
                if (_nameErr != null) ...[
                  const SizedBox(height: 8),
                  _errorText(_nameErr!),
                ],
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: _busyName ? null : _submitName,
                  child: _busyName
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('تحديث الاسم'),
                ),
              ],
            ),
            const SizedBox(height: 24),
            // ── اسم المستخدم ────────────────────────────────
            _sectionCard(
              context,
              title: 'اسم المستخدم',
              subtitle:
                  'اسم المستخدم مستخدم لتسجيل الدخول. يتطلّب تأكيد كلمة المرور الحالية.\n'
                  '٣-٣٢ حرفًا لاتينيًا أو رقمًا، مع نقطة أو شرطة سفلية أو شرطة (. _ -).',
              children: [
                Text(
                  'الحالي: $currentUsername',
                  style: TextStyle(color: context.tokens.muted, fontSize: 12),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _newUsernameCtrl,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: 'اسم المستخدم الجديد',
                    prefixIcon: Icon(Icons.badge_outlined),
                    hintText: 'مثال: ali.mohamed',
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _currentPasswordCtrl,
                  obscureText: _hidePassword,
                  textInputAction: TextInputAction.done,
                  decoration: InputDecoration(
                    labelText: 'كلمة المرور الحالية',
                    prefixIcon: const Icon(Icons.lock_outline),
                    suffixIcon: IconButton(
                      tooltip: _hidePassword
                          ? 'إظهار كلمة المرور'
                          : 'إخفاء كلمة المرور',
                      icon: Icon(_hidePassword
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined),
                      onPressed: () =>
                          setState(() => _hidePassword = !_hidePassword),
                    ),
                  ),
                ),
                if (_usernameErr != null) ...[
                  const SizedBox(height: 8),
                  _errorText(_usernameErr!),
                ],
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: _busyUsername ? null : _submitUsername,
                  child: _busyUsername
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('تحديث اسم المستخدم'),
                ),
              ],
            ),
            const SizedBox(height: 24),
            OutlinedButton.icon(
              onPressed: () => context.pop(),
              icon: const Icon(Icons.arrow_back),
              label: const Text('رجوع'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _sectionCard(
    BuildContext context, {
    required String title,
    required String subtitle,
    required List<Widget> children,
  }) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              title,
              style: TextStyle(
                color: Theme.of(context).colorScheme.primary,
                fontWeight: FontWeight.w800,
                fontSize: 15,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              subtitle,
              style: TextStyle(color: context.tokens.muted, fontSize: 12),
            ),
            const SizedBox(height: 14),
            ...children,
          ],
        ),
      ),
    );
  }

  Widget _errorText(String msg) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: AppColors.danger.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: AppColors.danger.withValues(alpha: 0.4)),
        ),
        child: Text(
          msg,
          style: TextStyle(
            color: Color.lerp(AppColors.ink, AppColors.danger, 0.35),
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      );
}

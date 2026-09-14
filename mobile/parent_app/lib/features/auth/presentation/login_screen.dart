import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../../../core/env.dart';
import '../application/auth_controller.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _busy = false;
  bool _hidePass = true;
  String? _err;

  @override
  void dispose() {
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _err = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .signIn(_userCtrl.text.trim(), _passCtrl.text);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _err = e.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _err = 'لم نتمكن من تسجيل دخولك — تحقق من الاتصال وحاول مجددًا');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authControllerProvider);
    final flashMsg = authState is Unauthenticated ? authState.lastMessage : null;

    return Scaffold(
      backgroundColor: AppColors.navy,
      body: Stack(
        fit: StackFit.expand,
        children: [
          const ArabesqueBackground(),
          SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Card(
                color: Colors.white,
                surfaceTintColor: Colors.white,
                elevation: 4,
                shadowColor: Colors.black45,
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        // Day 12 hot-fix — the raw 160-dp image sat awkwardly
                        // as a bare rectangle over a white card. Present it
                        // as a soft round medallion with a gold ring + drop
                        // shadow so the brand mark reads as a "seal" rather
                        // than a loose asset.
                        Center(
                          child: Container(
                            width: 132,
                            height: 132,
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: Colors.white,
                              shape: BoxShape.circle,
                              border: Border.all(color: AppColors.gold, width: 2),
                              boxShadow: [
                                BoxShadow(
                                  color: AppColors.navy.withValues(alpha: 0.10),
                                  blurRadius: 18,
                                  offset: const Offset(0, 6),
                                ),
                              ],
                            ),
                            child: const ManasetyLogo(
                              variant: ManasetyLogoVariant.emblem,
                              size: 104,
                            ),
                          ),
                        ),
                        const SizedBox(height: 14),
                        Container(
                          height: 3,
                          width: 56,
                          margin: const EdgeInsets.symmetric(vertical: 6),
                          decoration: BoxDecoration(
                            color: AppColors.gold,
                            borderRadius: BorderRadius.circular(2),
                          ),
                        ),
                        const SizedBox(height: 6),
                        const Center(
                          child: Text(
                            'بوابة ولي الأمر',
                            style: TextStyle(
                              color: AppColors.navy,
                              fontWeight: FontWeight.w700,
                              fontSize: 16,
                            ),
                          ),
                        ),
                        const SizedBox(height: 4),
                        const Center(
                          child: Text(
                            Env.institutionNameAr,
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: AppColors.muted,
                              fontSize: 12,
                            ),
                          ),
                        ),
                        const SizedBox(height: 22),
                        if (flashMsg != null) ...[
                          _flash(flashMsg, color: AppColors.gold),
                          const SizedBox(height: 12),
                        ],
                        if (_err != null) ...[
                          _flash(_err!, color: AppColors.danger),
                          const SizedBox(height: 12),
                        ],
                        TextFormField(
                          controller: _userCtrl,
                          autofillHints: const [AutofillHints.username],
                          textInputAction: TextInputAction.next,
                          style: const TextStyle(color: AppColors.ink),
                          decoration: _lightInput('اسم المستخدم'),
                          validator: (v) => (v == null || v.trim().isEmpty)
                              ? 'مطلوب'
                              : null,
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _passCtrl,
                          obscureText: _hidePass,
                          autofillHints: const [AutofillHints.password],
                          textInputAction: TextInputAction.done,
                          style: const TextStyle(color: AppColors.ink),
                          decoration: _lightInput('كلمة المرور').copyWith(
                            suffixIcon: IconButton(
                              tooltip: _hidePass
                                  ? 'إظهار كلمة المرور'
                                  : 'إخفاء كلمة المرور',
                              icon: Icon(
                                _hidePass
                                    ? Icons.visibility_outlined
                                    : Icons.visibility_off_outlined,
                                color: AppColors.muted,
                              ),
                              onPressed: () =>
                                  setState(() => _hidePass = !_hidePass),
                            ),
                          ),
                          onFieldSubmitted: (_) => _submit(),
                          validator: (v) => (v == null || v.isEmpty)
                              ? 'مطلوب'
                              : null,
                        ),
                        const SizedBox(height: 18),
                        ElevatedButton(
                          onPressed: _busy ? null : _submit,
                          child: _busy
                              ? const SizedBox(
                                  height: 18,
                                  width: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.white,
                                  ),
                                )
                              : const Text('دخول'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
          ),
        ],  // Stack children
      ),
    );
  }

  /// Explicit light-mode input decoration — the login card is always white,
  /// so we override the app-level (possibly dark) InputDecorationTheme.
  InputDecoration _lightInput(String label) {
    return InputDecoration(
      labelText: label,
      filled: true,
      fillColor: Colors.white,
      labelStyle: const TextStyle(color: AppColors.muted),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.navy, width: 1.6),
      ),
    );
  }

  Widget _flash(String msg, {required Color color}) {
    // Day 12 hot-fix — text used the same [color] as the tint background;
    // gold flashes were essentially invisible. Lerp toward ink for legibility
    // while keeping [color] on the bg tint + border so the intent still reads.
    final textColor = Color.lerp(AppColors.ink, color, 0.35)!;
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(
        msg,
        style: TextStyle(color: textColor, fontSize: 13, fontWeight: FontWeight.w600),
      ),
    );
  }
}

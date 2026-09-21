import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/router/routes.dart';
import '../../../core/storage/secure_storage.dart';
import '../../../shared/brand/manasety_wordmark.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _userCtrl = TextEditingController();
  final _pwdCtrl = TextEditingController();
  bool _obscure = true;
  bool _remember = true;
  bool _busy = false;
  String? _error;

  Future<void> _submit() async {
    if (_userCtrl.text.trim().isEmpty || _pwdCtrl.text.isEmpty) {
      setState(() => _error = 'أدخل اسم المستخدم وكلمة المرور.');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final dio = ref.read(dioProvider);
      final r = await dio.post(Endpoints.login, data: {
        'username': _userCtrl.text.trim(),
        'password': _pwdCtrl.text,
      });
      final token = (r.data as Map)['token'] as String?;
      if (token == null) throw const ServerException('لم يتم استلام رمز الجلسة.');
      final storage = ref.read(secureStorageProvider);
      await storage.writeToken(token);
      if (!mounted) return;
      context.go(Routes.home);
    } on DioException catch (e) {
      setState(() => _error = toApi(e).message);
    } catch (_) {
      setState(() => _error = 'تعذّر تسجيل الدخول.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Column(
            children: [
              const Spacer(),
              // Official Manasety wordmark (same SVG the web ships).
              const ManasetyWordmark(height: 72),
              const SizedBox(height: 12),
              const Text('نظام إدارة التعلم K-12',
                style: TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
              const SizedBox(height: 32),

              _Field(
                label: 'رقم الجوال أو اسم المستخدم',
                controller: _userCtrl,
                keyboardType: TextInputType.text,
              ),
              const SizedBox(height: 16),
              _Field(
                label: 'كلمة المرور',
                controller: _pwdCtrl,
                obscure: _obscure,
                suffix: IconButton(
                  icon: Icon(_obscure ? Icons.visibility_off_rounded : Icons.visibility_rounded),
                  onPressed: () => setState(() => _obscure = !_obscure),
                ),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Checkbox(
                    value: _remember,
                    onChanged: (v) => setState(() => _remember = v ?? true),
                    activeColor: ManasetyBrand.navy,
                  ),
                  const Text('تذكّرني'),
                  const Spacer(),
                  TextButton(
                    onPressed: () {},
                    child: const Text('نسيت كلمة المرور؟', style: TextStyle(color: ManasetyBrand.navy, fontWeight: FontWeight.w600)),
                  ),
                ],
              ),
              if (_error != null) Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(_error!, style: const TextStyle(color: ManasetyBrand.error)),
              ),
              const SizedBox(height: 16),
              _PrimaryGradientButton(
                label: _busy ? 'جارٍ الدخول…' : 'تسجيل الدخول',
                onPressed: _busy ? null : _submit,
              ),
              const Spacer(),
              const Opacity(opacity: 0.5, child: Text('منصتي',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: ManasetyBrand.outline))),
            ],
          ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({
    required this.label,
    required this.controller,
    this.obscure = false,
    this.suffix,
    this.keyboardType,
  });

  final String label;
  final TextEditingController controller;
  final bool obscure;
  final Widget? suffix;
  final TextInputType? keyboardType;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: ManasetyBrand.onSurface)),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          obscureText: obscure,
          keyboardType: keyboardType,
          decoration: InputDecoration(
            filled: true,
            fillColor: ManasetyBrand.surfaceContainerLow,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
              borderSide: BorderSide.none,
            ),
            suffixIcon: suffix,
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          ),
        ),
      ],
    );
  }
}

class _PrimaryGradientButton extends StatelessWidget {
  const _PrimaryGradientButton({required this.label, this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 48,
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: onPressed == null ? null : ManasetyBrand.primaryGradient,
          color: onPressed == null ? ManasetyBrand.outline : null,
          borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
          boxShadow: ManasetyBrand.shadowRaised,
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: onPressed,
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
            child: Center(
              child: Text(label,
                style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700)),
            ),
          ),
        ),
      ),
    );
  }
}

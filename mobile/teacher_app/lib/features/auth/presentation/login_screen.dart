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

/// [TCH] Login — matches `design_refs/tch/login.png`.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _S();
}

class _S extends ConsumerState<LoginScreen> {
  final _u = TextEditingController();
  final _p = TextEditingController();
  bool _obscure = true;
  bool _remember = true;
  bool _busy = false;
  String? _error;

  @override
  void dispose() { _u.dispose(); _p.dispose(); super.dispose(); }

  Future<void> _submit() async {
    if (_u.text.trim().isEmpty || _p.text.isEmpty) {
      setState(() => _error = 'أدخل البريد الإلكتروني وكلمة المرور.');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final r = await ref.read(dioProvider).post(Endpoints.login,
        data: {'username': _u.text.trim(), 'password': _p.text});
      final tok = (r.data as Map)['token'] as String?;
      if (tok == null) throw const ServerException('لم يتم استلام رمز الجلسة.');
      await ref.read(secureStorageProvider).writeToken(tok);
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
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: const Color(0xFFF3F6FB),
    body: SafeArea(child: SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
      child: Column(children: [
        _TopBar(),
        const SizedBox(height: 24),
        _LogoTile(),
        const SizedBox(height: 14),
        const Text('منصتي',
          style: TextStyle(fontSize: 34, fontWeight: FontWeight.w800,
            color: ManasetyBrand.navy, letterSpacing: -0.5)),
        const SizedBox(height: 4),
        const Text('بوابة المعلم الأكاديمية · نظام إدارة التعلم',
          style: TextStyle(fontSize: 13, color: ManasetyBrand.onSurfaceVariant)),
        const SizedBox(height: 20),
        const _HeroCard(),
        const SizedBox(height: 12),
        const _FeatureChip(),
        const SizedBox(height: 16),
        _LoginCard(
          u: _u, p: _p, obscure: _obscure, remember: _remember, busy: _busy, error: _error,
          onToggleObscure: () => setState(() => _obscure = !_obscure),
          onToggleRemember: (v) => setState(() => _remember = v ?? true),
          onSubmit: _submit,
        ),
        const SizedBox(height: 16),
        const _QuoteCard(),
        const SizedBox(height: 12),
        const _SecurityFooter(),
      ]),
    )),
  );
}

class _TopBar extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Row(children: [
    // Right (arrow back-to-portal) — RTL: this widget is on the visual right
    _CircleBtn(icon: Icons.arrow_forward_rounded, onPressed: () {}),
    const Spacer(),
    // Center portal chip
    Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFFDBEAFE),
        borderRadius: BorderRadius.circular(999),
      ),
      child: const Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.badge_rounded, size: 14, color: ManasetyBrand.navy),
        SizedBox(width: 6),
        Text('بوابة المعلم الأكاديمية',
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: ManasetyBrand.navy)),
      ])),
    const Spacer(),
    // Left (English) — RTL: this widget is on the visual left
    Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: const Text('English',
        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: ManasetyBrand.onSurface))),
  ]);
}

class _CircleBtn extends StatelessWidget {
  const _CircleBtn({required this.icon, required this.onPressed});
  final IconData icon; final VoidCallback onPressed;
  @override
  Widget build(BuildContext context) => Material(
    color: Colors.white,
    shape: const CircleBorder(side: BorderSide(color: Color(0xFFE2E8F0))),
    child: InkWell(onTap: onPressed, customBorder: const CircleBorder(),
      child: const Padding(padding: EdgeInsets.all(10),
        child: Icon(Icons.arrow_forward_rounded, size: 18, color: ManasetyBrand.onSurface))),
  );
}

class _LogoTile extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Container(
    width: 88, height: 88,
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(22),
      border: Border.all(color: const Color(0xFFDBEAFE)),
      boxShadow: ManasetyBrand.shadowDefault,
    ),
    child: const Padding(padding: EdgeInsets.all(16),
      child: ManasetyWordmark()),
  );
}

class _HeroCard extends StatelessWidget {
  const _HeroCard();
  @override
  Widget build(BuildContext context) => AspectRatio(
    aspectRatio: 16 / 9,
    child: Container(decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(ManasetyBrand.radiusLg),
      gradient: const LinearGradient(
        begin: Alignment.topRight, end: Alignment.bottomLeft,
        colors: [Color(0xFFDBEAFE), Color(0xFFE0F2FE), Color(0xFFFDE68A)],
      ),
      boxShadow: ManasetyBrand.shadowDefault,
    ), child: Stack(children: [
      Positioned(right: 20, top: 20, child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: Colors.white,
          borderRadius: BorderRadius.circular(6),
          boxShadow: ManasetyBrand.shadowDefault),
        child: const Text('TCH', style: TextStyle(fontSize: 10,
          fontWeight: FontWeight.w800, color: ManasetyBrand.navy)))),
      Center(child: Container(width: 140, height: 90,
        decoration: BoxDecoration(color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          boxShadow: ManasetyBrand.shadowRaised),
        child: const Icon(Icons.laptop_mac_rounded, size: 56, color: ManasetyBrand.navy))),
    ])),
  );
}

class _FeatureChip extends StatelessWidget {
  const _FeatureChip();
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Container(width: 40, height: 40,
        decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
          borderRadius: BorderRadius.circular(10)),
        child: const Icon(Icons.menu_book_rounded, color: ManasetyBrand.navy, size: 22)),
      const SizedBox(width: 12),
      const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('وصول مباشر وسريع للمعلمين',
          style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
        SizedBox(height: 2),
        Text('تحضير الدروس، رصد الغياب، ومتابعة الفصول الدراسية',
          style: TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
      ])),
    ]),
  );
}

class _LoginCard extends StatelessWidget {
  const _LoginCard({
    required this.u, required this.p,
    required this.obscure, required this.remember,
    required this.busy, required this.error,
    required this.onToggleObscure,
    required this.onToggleRemember,
    required this.onSubmit,
  });
  final TextEditingController u, p;
  final bool obscure, remember, busy;
  final String? error;
  final VoidCallback onToggleObscure, onSubmit;
  final ValueChanged<bool?> onToggleRemember;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(ManasetyBrand.radiusLg),
      border: Border.all(color: const Color(0xFFE2E8F0)),
      boxShadow: ManasetyBrand.shadowDefault),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('تسجيل الدخول',
        style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
      const SizedBox(height: 4),
      const Text('أهلاً بك مجدداً. سجّل دخولك لإدارة فصولك وجدولك الدراسي',
        style: TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
      const SizedBox(height: 20),
      const _FieldLabel('البريد الإلكتروني أو رقم الهوية'),
      _TextField(controller: u, hint: 'name@school.edu.sa',
        leading: const Icon(Icons.alternate_email_rounded, size: 18, color: ManasetyBrand.onSurfaceVariant)),
      const SizedBox(height: 14),
      const _FieldLabel('كلمة المرور'),
      _TextField(controller: p, obscure: obscure, hint: '••••••••',
        leading: const Icon(Icons.lock_outline_rounded, size: 18, color: ManasetyBrand.onSurfaceVariant),
        trailing: IconButton(
          onPressed: onToggleObscure, splashRadius: 18, iconSize: 18,
          icon: Icon(obscure ? Icons.visibility_off_rounded : Icons.visibility_rounded,
            color: ManasetyBrand.onSurfaceVariant))),
      const SizedBox(height: 6),
      Row(children: [
        TextButton(onPressed: () {},
          style: TextButton.styleFrom(padding: EdgeInsets.zero, minimumSize: const Size(0, 32)),
          child: const Text('نسيت كلمة المرور؟',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: ManasetyBrand.blue))),
        const Spacer(),
        const Text('تذكّرني', style: TextStyle(fontSize: 12, color: ManasetyBrand.onSurface)),
        SizedBox(width: 20, height: 20, child: Checkbox(
          value: remember, onChanged: onToggleRemember,
          activeColor: ManasetyBrand.navy,
          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap)),
      ]),
      if (error != null) Padding(padding: const EdgeInsets.only(top: 8),
        child: Text(error!, style: const TextStyle(color: ManasetyBrand.error, fontSize: 12))),
      const SizedBox(height: 14),
      SizedBox(width: double.infinity, height: 52,
        child: DecoratedBox(decoration: BoxDecoration(
          gradient: ManasetyBrand.primaryGradient,
          borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
          boxShadow: ManasetyBrand.shadowRaised),
          child: Material(color: Colors.transparent, child: InkWell(
            onTap: busy ? null : onSubmit,
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
            child: Center(child: Row(mainAxisSize: MainAxisSize.min, children: [
              Text(busy ? 'جارٍ الدخول…' : 'تسجيل الدخول',
                style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)),
              const SizedBox(width: 8),
              const Icon(Icons.arrow_back_rounded, color: Colors.white, size: 18),
            ]))),
          ))),
      const SizedBox(height: 16),
      Row(children: [
        Expanded(child: Container(height: 1, color: const Color(0xFFE2E8F0))),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 8),
          child: const Text('أو الدخول عبر النفاذ الوطني الموحد',
            style: TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant))),
        Expanded(child: Container(height: 1, color: const Color(0xFFE2E8F0))),
      ]),
      const SizedBox(height: 12),
      SizedBox(width: double.infinity, height: 44,
        child: OutlinedButton.icon(
          onPressed: () {},
          icon: const Icon(Icons.fingerprint_rounded, size: 20, color: Color(0xFF10B981)),
          label: const Text('الدخول بواسطة النفاذ الوطني',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
          style: OutlinedButton.styleFrom(
            backgroundColor: const Color(0xFFF3F6FB),
            side: const BorderSide(color: Color(0xFFE2E8F0)),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd))))),
    ]),
  );
}

class _FieldLabel extends StatelessWidget {
  const _FieldLabel(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Text(text,
      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)));
}

class _TextField extends StatelessWidget {
  const _TextField({required this.controller, this.hint, this.obscure = false,
    this.leading, this.trailing});
  final TextEditingController controller;
  final String? hint;
  final bool obscure;
  final Widget? leading, trailing;
  @override
  Widget build(BuildContext context) => TextField(
    controller: controller, obscureText: obscure,
    decoration: InputDecoration(
      filled: true, fillColor: const Color(0xFFF3F6FB), hintText: hint,
      hintStyle: const TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 13),
      prefixIcon: trailing, suffixIcon: leading,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
        borderSide: const BorderSide(color: Color(0xFFE2E8F0))),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
        borderSide: const BorderSide(color: Color(0xFFE2E8F0))),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
        borderSide: const BorderSide(color: ManasetyBrand.blue)),
    ));
}

class _QuoteCard extends StatelessWidget {
  const _QuoteCard();
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Container(padding: const EdgeInsets.all(6),
        decoration: BoxDecoration(color: const Color(0xFFFEF3C7),
          borderRadius: BorderRadius.circular(8)),
        child: const Icon(Icons.star_rounded, color: Color(0xFFF59E0B), size: 16)),
      const SizedBox(width: 10),
      const Expanded(child: Text(
        '«المعلم شعلة الأثر… يومٌ دراسي ملهم لك ولطلابك»',
        style: TextStyle(fontSize: 12, color: ManasetyBrand.onSurface, height: 1.35))),
    ]),
  );
}

class _SecurityFooter extends StatelessWidget {
  const _SecurityFooter();
  @override
  Widget build(BuildContext context) => Column(children: [
    const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
      Icon(Icons.shield_rounded, size: 14, color: Color(0xFF10B981)),
      SizedBox(width: 6),
      Text('بوابة آمنة ومحمية بتشفير عالي الأمان',
        style: TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant, fontWeight: FontWeight.w600)),
    ]),
    const SizedBox(height: 4),
    const Text('منصتي · نظام منصتي الموحد © 2025 وزارة التعليم',
      style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
  ]);
}

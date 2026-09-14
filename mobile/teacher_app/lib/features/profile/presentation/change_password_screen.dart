import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
class ChangePasswordScreen extends ConsumerStatefulWidget {
  const ChangePasswordScreen({super.key});
  @override
  ConsumerState<ChangePasswordScreen> createState() =>
      _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends ConsumerState<ChangePasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _oldCtl = TextEditingController();
  final _newCtl = TextEditingController();
  final _confirmCtl = TextEditingController();
  bool _busy = false;
  bool _hideOld = true;
  bool _hideNew = true;
  String? _serverErr;

  @override
  void dispose() {
    _oldCtl.dispose();
    _newCtl.dispose();
    _confirmCtl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _serverErr = null);
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      final dio = ref.read(dioProvider);
      await dio.post(Endpoints.changePassword, data: {
        'old_password': _oldCtl.text,
        'new_password': _newCtl.text,
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تمّ تغيير كلمة المرور — سجّل الدخول بها في المرة القادمة ✓'),
          backgroundColor: AppColors.success,
        ),
      );
      context.pop();
    } catch (e) {
      final api = toApi(e);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _serverErr = api is UnauthorizedException
            ? 'كلمة المرور الحالية غير صحيحة'
            : api.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('تغيير كلمة المرور')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: _oldCtl,
                obscureText: _hideOld,
                autofocus: true,
                decoration: InputDecoration(
                  labelText: 'كلمة المرور الحالية',
                  suffixIcon: IconButton(
                    tooltip: _hideOld
                        ? 'إظهار كلمة المرور'
                        : 'إخفاء كلمة المرور',
                    icon: Icon(_hideOld
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined),
                    onPressed: () => setState(() => _hideOld = !_hideOld),
                  ),
                ),
                validator: (v) => (v == null || v.isEmpty) ? 'مطلوب' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _newCtl,
                obscureText: _hideNew,
                decoration: InputDecoration(
                  labelText: 'كلمة المرور الجديدة (٨ أحرف على الأقل)',
                  suffixIcon: IconButton(
                    tooltip: _hideNew
                        ? 'إظهار كلمة المرور'
                        : 'إخفاء كلمة المرور',
                    icon: Icon(_hideNew
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined),
                    onPressed: () => setState(() => _hideNew = !_hideNew),
                  ),
                ),
                validator: (v) =>
                    (v == null || v.length < 8) ? '٨ أحرف على الأقل' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _confirmCtl,
                obscureText: _hideNew,
                decoration: const InputDecoration(
                    labelText: 'تأكيد كلمة المرور الجديدة'),
                validator: (v) =>
                    v != _newCtl.text ? 'كلمتا المرور غير متطابقتين' : null,
              ),
              if (_serverErr != null) ...[
                const SizedBox(height: 16),
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppColors.danger.withValues(alpha: 0.1),
                    border: Border.all(color: AppColors.danger),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(_serverErr!,
                      style: const TextStyle(
                          color: AppColors.danger, fontWeight: FontWeight.w600)),
                ),
              ],
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: _busy ? null : _submit,
                style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                child: _busy
                    ? const SizedBox(
                        height: 20, width: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Text('حفظ',
                        style: TextStyle(fontWeight: FontWeight.w800)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

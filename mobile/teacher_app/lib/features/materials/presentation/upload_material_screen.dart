import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../../../shared/models/section_brief.dart';
import '../../sections/data/sections_repository.dart';
import '../data/materials_repository.dart';

enum _Kind { link, file }

class UploadMaterialScreen extends ConsumerStatefulWidget {
  const UploadMaterialScreen({super.key});
  @override
  ConsumerState<UploadMaterialScreen> createState() =>
      _UploadMaterialScreenState();
}

class _UploadMaterialScreenState extends ConsumerState<UploadMaterialScreen> {
  final _titleCtl = TextEditingController();
  final _descCtl = TextEditingController();
  final _urlCtl = TextEditingController();
  int? _sectionId;
  int? _subjectId;
  _Kind _kind = _Kind.file;
  String? _filePath;
  String? _fileName;
  double _progress = 0;
  bool _busy = false;
  String? _err;

  @override
  void dispose() {
    _titleCtl.dispose();
    _descCtl.dispose();
    _urlCtl.dispose();
    super.dispose();
  }

  Future<void> _pickFile() async {
    final res = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf', 'jpg', 'jpeg', 'png'],
    );
    if (res != null && res.files.single.path != null) {
      setState(() {
        _filePath = res.files.single.path;
        _fileName = res.files.single.name;
      });
    }
  }

  Future<void> _pickImage(ImageSource source) async {
    final picker = ImagePicker();
    final img = await picker.pickImage(source: source, imageQuality: 85);
    if (img != null) {
      setState(() {
        _filePath = img.path;
        _fileName = img.name;
      });
    }
  }

  Future<void> _submit() async {
    if (_sectionId == null || _subjectId == null) {
      setState(() => _err = 'اختر الفصل والمادة أولًا.');
      return;
    }
    if (_titleCtl.text.trim().isEmpty) {
      setState(() => _err = 'العنوان مطلوب.');
      return;
    }
    setState(() {
      _busy = true;
      _err = null;
      _progress = 0;
    });
    try {
      final repo = ref.read(materialsRepositoryProvider);
      if (_kind == _Kind.link) {
        if (_urlCtl.text.trim().isEmpty) {
          throw const ValidationException('الرابط مطلوب');
        }
        await repo.createLink(
          sectionId: _sectionId!,
          subjectId: _subjectId!,
          title: _titleCtl.text.trim(),
          description: _descCtl.text.trim().isEmpty
              ? null
              : _descCtl.text.trim(),
          url: _urlCtl.text.trim(),
        );
      } else {
        if (_filePath == null) {
          throw const ValidationException('اختر ملفًا للرفع');
        }
        await repo.uploadFile(
          sectionId: _sectionId!,
          subjectId: _subjectId!,
          title: _titleCtl.text.trim(),
          description: _descCtl.text.trim().isEmpty
              ? null
              : _descCtl.text.trim(),
          filePath: _filePath!,
          onProgress: (sent, total) {
            if (total > 0 && mounted) {
              setState(() => _progress = sent / total);
            }
          },
        );
      }
      // Refresh the materials list on return
      ref.invalidate(teacherMaterialsProvider);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تمّ رفع المادة — ستظهر لطلاب فصلك حالًا ✓'),
          backgroundColor: AppColors.success,
        ),
      );
      context.pop();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _err = e.message;
        _busy = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _err = e.toString();
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final sectionsAsync = ref.watch(sectionsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('رفع مادة جديدة')),
      body: AsyncValueWidget<List<SectionBrief>>(
        value: sectionsAsync,
        data: (sections) {
          final section = _sectionId == null
              ? null
              : sections.firstWhere(
                  (s) => s.id == _sectionId,
                  orElse: () => sections.first,
                );
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              DropdownButtonFormField<int>(
                initialValue: _sectionId,
                decoration: const InputDecoration(labelText: 'الفصل'),
                items: sections.map((s) => DropdownMenuItem(
                  value: s.id, child: Text(s.name),
                )).toList(),
                onChanged: (v) => setState(() {
                  _sectionId = v;
                  _subjectId = null;
                }),
              ),
              const SizedBox(height: 12),
              if (section != null)
                DropdownButtonFormField<int>(
                  initialValue: _subjectId,
                  decoration: const InputDecoration(labelText: 'المادة'),
                  items: section.subjects.map((s) => DropdownMenuItem(
                    value: s.id, child: Text(s.name),
                  )).toList(),
                  onChanged: (v) => setState(() => _subjectId = v),
                ),
              const SizedBox(height: 12),
              TextField(
                controller: _titleCtl,
                decoration: const InputDecoration(labelText: 'عنوان المادة'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _descCtl,
                maxLines: 2,
                decoration:
                    const InputDecoration(labelText: 'وصف (اختياري)'),
              ),
              const SizedBox(height: 20),
              SegmentedButton<_Kind>(
                segments: const [
                  ButtonSegment(
                      value: _Kind.file, label: Text('ملف / صورة'), icon: Icon(Icons.upload_file)),
                  ButtonSegment(
                      value: _Kind.link, label: Text('رابط'), icon: Icon(Icons.link)),
                ],
                selected: {_kind},
                onSelectionChanged: (s) => setState(() => _kind = s.first),
              ),
              const SizedBox(height: 12),
              if (_kind == _Kind.link)
                TextField(
                  controller: _urlCtl,
                  keyboardType: TextInputType.url,
                  decoration: const InputDecoration(
                    labelText: 'الرابط (URL)',
                    hintText: 'https://...',
                  ),
                )
              else ...[
                Row(children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _pickFile,
                      icon: const Icon(Icons.picture_as_pdf_outlined),
                      label: const Text('اختر ملف PDF/صورة'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    tooltip: 'من الكاميرا',
                    onPressed: () => _pickImage(ImageSource.camera),
                    icon: const Icon(Icons.photo_camera),
                    color: AppColors.navy,
                  ),
                  IconButton(
                    tooltip: 'من المعرض',
                    onPressed: () => _pickImage(ImageSource.gallery),
                    icon: const Icon(Icons.photo_library),
                    color: AppColors.navy,
                  ),
                ]),
                if (_fileName != null) ...[
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: AppColors.sky.withValues(alpha: 0.3),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.check_circle,
                            color: AppColors.success, size: 18),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _fileName!,
                            style: TextStyle(
                                fontWeight: FontWeight.w700, color: context.tokens.ink),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
              if (_progress > 0 && _busy) ...[
                const SizedBox(height: 12),
                LinearProgressIndicator(value: _progress),
                const SizedBox(height: 4),
                Text('${(_progress * 100).toStringAsFixed(0)}٪',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: context.tokens.muted, fontSize: 12)),
              ],
              if (_err != null) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppColors.danger.withValues(alpha: 0.1),
                    border: Border.all(color: AppColors.danger),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(_err!,
                      style: const TextStyle(
                          color: AppColors.danger, fontWeight: FontWeight.w600)),
                ),
              ],
              const SizedBox(height: 20),
              ElevatedButton(
                onPressed: _busy ? null : _submit,
                style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                child: _busy
                    ? const SizedBox(
                        height: 20, width: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Text('رفع المادة',
                        style: TextStyle(fontWeight: FontWeight.w800)),
              ),
            ],
          );
        },
      ),
    );
  }
}

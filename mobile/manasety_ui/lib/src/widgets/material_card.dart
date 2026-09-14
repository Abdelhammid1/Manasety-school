import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/material_item.dart';
import '../theme/colors.dart';
import '../theme/tokens.dart';
import 'status_chip.dart';
import 'tinted_icon_avatar.dart';

class MaterialCard extends StatelessWidget {
  final MaterialItem item;

  /// Base URL used to resolve relative [MaterialItem.filePath] values into
  /// absolute HTTP(S) URLs. Callers pass `Env.apiBase.replaceAll('/api', '')`.
  final String fileBaseUrl;

  const MaterialCard({
    super.key,
    required this.item,
    required this.fileBaseUrl,
  });

  IconData _icon() {
    switch (item.kind) {
      case MaterialKind.file:
        return Icons.picture_as_pdf_outlined;
      case MaterialKind.video:
        return Icons.play_circle_outline;
      case MaterialKind.link:
        return Icons.link;
      case MaterialKind.unknown:
        return Icons.insert_drive_file_outlined;
    }
  }

  Future<void> _open() async {
    final url = item.externalUrl?.isNotEmpty == true
        ? item.externalUrl!
        : (item.filePath != null
            ? '$fileBaseUrl${item.filePath}'
            : null);
    if (url == null) return;
    final uri = Uri.tryParse(url);
    if (uri == null) return;
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TintedIconAvatar(icon: _icon(), size: 44),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.title,
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 15,
                      color: t.ink,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${item.subjectName} • ${item.sectionName}',
                    style: TextStyle(
                      color: t.muted,
                      fontSize: 12,
                    ),
                  ),
                  if (item.description != null &&
                      item.description!.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      item.description!,
                      style: TextStyle(
                        color: t.ink,
                        fontSize: 13,
                      ),
                    ),
                  ],
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      if (!item.hasOpenable)
                        const StatusChip(
                          label: 'ملف غير متاح حاليًا',
                          kind: StatusKind.neutral,
                        )
                      else
                        TextButton.icon(
                          onPressed: _open,
                          icon: const Icon(Icons.open_in_new, size: 16),
                          label: const Text('افتح'),
                          // Day 12 hot-fix — gold text on white card had
                          // ≈1.9:1 contrast; goldInk carries the same brand
                          // read at ≈5:1.
                          style: TextButton.styleFrom(
                            foregroundColor: AppColors.goldInk,
                            padding: EdgeInsets.zero,
                          ),
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

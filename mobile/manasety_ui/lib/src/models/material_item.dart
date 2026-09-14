enum MaterialKind { file, video, link, unknown }

MaterialKind _parseKind(String? k) {
  switch (k) {
    case 'file':
      return MaterialKind.file;
    case 'video':
      return MaterialKind.video;
    case 'link':
      return MaterialKind.link;
    default:
      return MaterialKind.unknown;
  }
}

class MaterialItem {
  final int id;
  final String title;
  final String? description;
  final MaterialKind kind;
  final String? externalUrl;
  final String? filePath;
  final String sectionName;
  final String subjectName;
  final DateTime createdAt;

  const MaterialItem({
    required this.id,
    required this.title,
    required this.kind,
    required this.sectionName,
    required this.subjectName,
    required this.createdAt,
    this.description,
    this.externalUrl,
    this.filePath,
  });

  factory MaterialItem.fromJson(Map<String, dynamic> j) => MaterialItem(
        id: j['id'] as int,
        title: (j['title'] ?? '') as String,
        description: j['description'] as String?,
        kind: _parseKind(j['kind'] as String?),
        externalUrl: j['external_url'] as String?,
        filePath: j['file_path'] as String?,
        sectionName: (j['section_name'] ?? '') as String,
        subjectName: (j['subject_name'] ?? '') as String,
        createdAt:
            DateTime.tryParse((j['created_at'] ?? '') as String) ?? DateTime.now(),
      );

  bool get hasOpenable =>
      (externalUrl != null && externalUrl!.isNotEmpty) ||
      (filePath != null && filePath!.isNotEmpty);
}

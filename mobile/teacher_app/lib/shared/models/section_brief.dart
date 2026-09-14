class SubjectBrief {
  final int id;
  final String name;
  const SubjectBrief({required this.id, required this.name});
  factory SubjectBrief.fromJson(Map<String, dynamic> j) =>
      SubjectBrief(id: j['id'] as int, name: j['name'] as String);
}

class SectionBrief {
  final int id;
  final String name;
  final List<SubjectBrief> subjects;
  const SectionBrief({
    required this.id,
    required this.name,
    required this.subjects,
  });

  factory SectionBrief.fromJson(Map<String, dynamic> j) {
    final raw = (j['subjects'] as List?) ?? const [];
    return SectionBrief(
      id: j['id'] as int,
      name: j['name'] as String,
      subjects:
          raw.map((e) => SubjectBrief.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }
}

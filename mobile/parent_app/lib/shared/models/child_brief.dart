class ChildBrief {
  final int id;
  final String permanentCode;
  final String fullName;
  final String? currentSection;
  final String? currentYear;

  const ChildBrief({
    required this.id,
    required this.permanentCode,
    required this.fullName,
    this.currentSection,
    this.currentYear,
  });

  factory ChildBrief.fromJson(Map<String, dynamic> j) => ChildBrief(
        id: j['id'] as int,
        permanentCode: (j['permanent_code'] ?? '') as String,
        fullName: (j['full_name'] ?? '') as String,
        currentSection: j['current_section'] as String?,
        currentYear: j['current_year'] as String?,
      );
}

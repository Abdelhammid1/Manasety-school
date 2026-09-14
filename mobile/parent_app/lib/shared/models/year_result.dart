class YearResult {
  final String year;
  final String grade;
  final String section;
  final String status; // pass/fail/conditional
  final double average;
  final Map<String, dynamic> subjectScores;
  final DateTime approvedAt;

  const YearResult({
    required this.year,
    required this.grade,
    required this.section,
    required this.status,
    required this.average,
    required this.subjectScores,
    required this.approvedAt,
  });

  factory YearResult.fromJson(Map<String, dynamic> j) => YearResult(
        year: (j['year'] ?? '') as String,
        grade: (j['grade'] ?? '') as String,
        section: (j['section'] ?? '') as String,
        status: (j['status'] ?? '') as String,
        average: ((j['average'] ?? 0) as num).toDouble(),
        subjectScores: (j['subject_scores'] as Map<String, dynamic>?) ?? const {},
        approvedAt:
            DateTime.tryParse((j['approved_at'] ?? '') as String) ?? DateTime.now(),
      );

  String get statusAr {
    switch (status) {
      case 'pass':
        return 'ناجح';
      case 'fail':
        return 'راسب';
      case 'conditional':
        return 'مشروط';
      default:
        return status;
    }
  }
}

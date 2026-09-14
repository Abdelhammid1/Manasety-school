class AssessmentComponentBrief {
  final int id;
  final String name;
  final double maxScore;

  const AssessmentComponentBrief({
    required this.id,
    required this.name,
    required this.maxScore,
  });

  factory AssessmentComponentBrief.fromJson(Map<String, dynamic> j) =>
      AssessmentComponentBrief(
        id: j['id'] as int,
        name: (j['name'] ?? '') as String,
        maxScore: ((j['max_score'] ?? 0) as num).toDouble(),
      );
}

class Term {
  final int id;
  final int yearId;
  final String name;
  final DateTime? startDate;
  final DateTime? endDate;

  const Term({
    required this.id,
    required this.yearId,
    required this.name,
    this.startDate,
    this.endDate,
  });

  factory Term.fromJson(Map<String, dynamic> j) => Term(
        id: j['id'] as int,
        yearId: j['year_id'] as int,
        name: j['name'] as String,
        startDate: j['start_date'] != null
            ? DateTime.tryParse(j['start_date'] as String)
            : null,
        endDate: j['end_date'] != null
            ? DateTime.tryParse(j['end_date'] as String)
            : null,
      );
}

class ScheduleSlot {
  final int dayId;
  final String dayName;
  final int periodId;
  final String periodName;
  final String startTime;
  final String endTime;
  final int subjectId;
  final String subjectName;
  final int? teacherId;
  final String? teacherName;
  final int? sectionId;
  final String? sectionName;

  const ScheduleSlot({
    required this.dayId,
    required this.dayName,
    required this.periodId,
    required this.periodName,
    required this.startTime,
    required this.endTime,
    required this.subjectId,
    required this.subjectName,
    this.teacherId,
    this.teacherName,
    this.sectionId,
    this.sectionName,
  });

  factory ScheduleSlot.fromJson(Map<String, dynamic> j) => ScheduleSlot(
        dayId: j['day_id'] as int,
        dayName: (j['day_name'] ?? '') as String,
        periodId: j['period_id'] as int,
        periodName: (j['period_name'] ?? '') as String,
        startTime: (j['start_time'] ?? '') as String,
        endTime: (j['end_time'] ?? '') as String,
        subjectId: j['subject_id'] as int,
        subjectName: (j['subject_name'] ?? '') as String,
        teacherId: j['teacher_id'] as int?,
        teacherName: j['teacher_name'] as String?,
        sectionId: j['section_id'] as int?,
        sectionName: j['section_name'] as String?,
      );
}

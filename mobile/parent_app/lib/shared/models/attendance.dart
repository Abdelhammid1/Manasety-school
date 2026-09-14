enum AttendanceStatus { present, absent, late, unknown }

AttendanceStatus _parseStatus(String? s) {
  switch (s) {
    case 'present':
      return AttendanceStatus.present;
    case 'absent':
      return AttendanceStatus.absent;
    case 'late':
      return AttendanceStatus.late;
    default:
      return AttendanceStatus.unknown;
  }
}

extension AttendanceStatusAr on AttendanceStatus {
  String get labelAr {
    switch (this) {
      case AttendanceStatus.present:
        return 'حاضر';
      case AttendanceStatus.absent:
        return 'غائب';
      case AttendanceStatus.late:
        return 'متأخّر';
      case AttendanceStatus.unknown:
        return '—';
    }
  }
}

class AttendanceSummary {
  final int present;
  final int absent;
  final int late;
  final int total;
  final double rate;

  const AttendanceSummary({
    required this.present,
    required this.absent,
    required this.late,
    required this.total,
    required this.rate,
  });

  factory AttendanceSummary.fromJson(Map<String, dynamic> j) =>
      AttendanceSummary(
        present: (j['present'] ?? 0) as int,
        absent: (j['absent'] ?? 0) as int,
        late: (j['late'] ?? 0) as int,
        total: (j['total'] ?? 0) as int,
        rate: ((j['rate'] ?? 0) as num).toDouble(),
      );
}

class AttendanceRecord {
  final DateTime date;
  final AttendanceStatus status;
  final String? notes;

  const AttendanceRecord({
    required this.date,
    required this.status,
    this.notes,
  });

  factory AttendanceRecord.fromJson(Map<String, dynamic> j) => AttendanceRecord(
        date: DateTime.parse(j['date'] as String),
        status: _parseStatus(j['status'] as String?),
        notes: j['notes'] as String?,
      );
}

class ChildAttendance {
  final AttendanceSummary summary;
  final List<AttendanceRecord> records;
  const ChildAttendance({required this.summary, required this.records});
}

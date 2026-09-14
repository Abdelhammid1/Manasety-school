/// حالات الحضور المعتمدة على السيرفر.
enum AttendanceStatus { present, absent, late }

extension AttendanceStatusX on AttendanceStatus {
  String get wire {
    switch (this) {
      case AttendanceStatus.present:
        return 'present';
      case AttendanceStatus.absent:
        return 'absent';
      case AttendanceStatus.late:
        return 'late';
    }
  }

  String get labelAr {
    switch (this) {
      case AttendanceStatus.present:
        return 'حاضر';
      case AttendanceStatus.absent:
        return 'غائب';
      case AttendanceStatus.late:
        return 'متأخّر';
    }
  }
}

AttendanceStatus? attendanceFromWire(String? s) {
  switch (s) {
    case 'present':
      return AttendanceStatus.present;
    case 'absent':
      return AttendanceStatus.absent;
    case 'late':
      return AttendanceStatus.late;
    default:
      return null;
  }
}

class AttendanceMark {
  final AttendanceStatus? status;
  final String? notes;
  final bool dirty;

  const AttendanceMark({this.status, this.notes, this.dirty = false});

  AttendanceMark copyWith({
    AttendanceStatus? status,
    String? notes,
    bool? dirty,
  }) => AttendanceMark(
        status: status ?? this.status,
        notes: notes ?? this.notes,
        dirty: dirty ?? this.dirty,
      );
}

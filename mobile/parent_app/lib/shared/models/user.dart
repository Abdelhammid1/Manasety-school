/// نموذج المستخدم المُعاد من /api/me و /api/auth/login.
class AppUser {
  final int id;
  final int? schoolId;
  final String username;
  final String fullName;
  final String? roleCode;
  final String? roleAr;
  final List<int> childrenIds;

  const AppUser({
    required this.id,
    required this.username,
    required this.fullName,
    this.schoolId,
    this.roleCode,
    this.roleAr,
    this.childrenIds = const [],
  });

  factory AppUser.fromJson(Map<String, dynamic> j) {
    final raw = (j['children_ids'] as List?) ?? const [];
    return AppUser(
      id: j['id'] as int,
      schoolId: j['school_id'] as int?,
      username: (j['username'] ?? '') as String,
      fullName: (j['full_name'] ?? '') as String,
      roleCode: j['role'] as String?,
      roleAr: j['role_ar'] as String?,
      childrenIds: raw.map((e) => e as int).toList(),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'school_id': schoolId,
        'username': username,
        'full_name': fullName,
        'role': roleCode,
        'role_ar': roleAr,
        'children_ids': childrenIds,
      };
}

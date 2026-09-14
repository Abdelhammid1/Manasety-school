class Routes {
  /// Day 13 (v3) — Flutter-side welcome splash (illuminated-manuscript
  /// design). Initial route on cold-launch; auto-navigates to [home] after
  /// ~1.4 s. The router redirect then re-routes to [login] or [home]
  /// based on auth state.
  static const welcome = '/welcome';
  static const login = '/login';
  static const home = '/';
  static String sectionDetail(int id) => '/sections/$id';
}

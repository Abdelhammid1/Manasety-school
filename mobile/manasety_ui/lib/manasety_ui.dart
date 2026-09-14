/// Public entry for the Manasety shared UI package.
///
/// Both `parent_app` and `teacher_app` import this single barrel:
///   import 'package:manasety_ui/manasety_ui.dart';
library;

// Theme
export 'src/theme/app_theme.dart';
export 'src/theme/arabize.dart';
export 'src/theme/colors.dart';
export 'src/theme/manasety_page_transitions.dart';
export 'src/theme/subject_palette.dart';
export 'src/theme/tokens.dart';
export 'src/theme/typography.dart';

// API error types (used by ErrorView; re-exported so apps can also match on them)
export 'src/api/api_exception.dart';

// Domain models used by the shared widgets
export 'src/models/material_item.dart';
export 'src/models/schedule_slot.dart';

// Widgets
export 'src/widgets/accent_rail_card.dart';
export 'src/widgets/app_refresh_indicator.dart';
export 'src/widgets/arabesque_background.dart';
export 'src/widgets/async_value_widget.dart';
export 'src/widgets/attendance_donut.dart';
export 'src/widgets/attendance_month_grid.dart';
export 'src/widgets/empty_illustration.dart';
export 'src/widgets/empty_state.dart';
export 'src/widgets/error_view.dart';
export 'src/widgets/greeting_card.dart';
export 'src/widgets/manasety_logo.dart';
export 'src/widgets/material_card.dart';
export 'src/widgets/notification_group_list.dart';
export 'src/widgets/refreshable_empty.dart';
export 'src/widgets/section_heading.dart';
export 'src/widgets/skeleton.dart';
export 'src/widgets/stat_row.dart';
export 'src/widgets/stat_tile.dart';
export 'src/widgets/status_chip.dart';
export 'src/widgets/subject_progress_bar.dart';
export 'src/widgets/tinted_icon_avatar.dart';
export 'src/widgets/weekly_schedule_grid.dart';

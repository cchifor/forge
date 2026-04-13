// Extensions on generated API types that add UI-specific or convenience logic.
// Kept outside the generated folder so they survive re-generation.
import 'generated/export.dart';

extension ItemStatusLabel on ItemStatus {
  String get label => switch (this) {
        ItemStatus.draft => 'Draft',
        ItemStatus.active => 'Active',
        ItemStatus.archived => 'Archived',
        ItemStatus.$unknown => 'Unknown',
      };
}

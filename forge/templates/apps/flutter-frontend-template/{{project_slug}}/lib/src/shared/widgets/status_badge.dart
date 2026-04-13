import 'package:flutter/material.dart';

import '../../api/generated/export.dart';
import '../../api/generated_extensions.dart';
import '../../theme/design_tokens.dart';

class StatusBadge extends StatelessWidget {
  const StatusBadge({required this.status, super.key});

  final ItemStatus status;

  @override
  Widget build(BuildContext context) {
    final (color, icon) = switch (status) {
      ItemStatus.draft => (Colors.orange, Icons.edit_outlined),
      ItemStatus.active => (Colors.green, Icons.check_circle_outline),
      ItemStatus.archived => (Colors.grey, Icons.archive_outlined),
      ItemStatus.$unknown => (Colors.grey, Icons.help_outline),
    };

    return Chip(
      avatar: Icon(icon, size: DesignTokens.iconSM, color: color),
      label: Text(
        status.label,
        style: TextStyle(color: color, fontSize: 12),
      ),
      visualDensity: VisualDensity.compact,
      padding: EdgeInsets.zero,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
  }
}

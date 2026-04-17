import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

class DataTableActivity extends StatelessWidget {
  const DataTableActivity({super.key, required this.activity});

  final WorkspaceActivity activity;

  List<Map<String, dynamic>> get _rows {
    final raw = activity.content['rows'];
    if (raw is List) {
      return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return const [];
  }

  List<Map<String, dynamic>> get _columns {
    final raw = activity.content['columns'];
    if (raw is List) {
      return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    final rows = _rows;
    if (rows.isNotEmpty) {
      return rows.first.keys.map((k) => {'key': k, 'label': k}).toList();
    }
    return const [];
  }

  String _format(dynamic v) {
    if (v == null) return '';
    if (v is Map || v is List) return v.toString();
    return v.toString();
  }

  @override
  Widget build(BuildContext context) {
    final rows = _rows;
    final cols = _columns;
    if (rows.isEmpty) {
      return const Center(child: Text('No rows.'));
    }
    return SingleChildScrollView(
      key: const ValueKey('canvas-data-table'),
      scrollDirection: Axis.horizontal,
      child: SingleChildScrollView(
        child: DataTable(
          columns: [
            for (final col in cols)
              DataColumn(
                label: Text((col['label'] ?? col['key'])?.toString() ?? ''),
              ),
          ],
          rows: [
            for (final row in rows)
              DataRow(
                cells: [
                  for (final col in cols)
                    DataCell(Text(_format(row[col['key']]))),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

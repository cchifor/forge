import 'dart:convert';

import 'package:flutter/material.dart';

/// DataTable canvas component — tabular data with sortable columns and
/// client-side pagination.
///
/// Props schema:
/// forge/templates/_shared/canvas-components/DataTable.props.schema.json
class DataTable extends StatefulWidget {
  final List<_Column> columns;
  final List<Map<String, dynamic>> rows;
  final int pageSize;

  DataTable({
    super.key,
    required List<Map<String, dynamic>> columns,
    required this.rows,
    this.pageSize = 25,
  }) : columns = columns.map(_Column.fromMap).toList(growable: false);

  factory DataTable.fromProps(Map<String, dynamic> props) => DataTable(
        columns: ((props['columns'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .toList(),
        rows: ((props['rows'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .toList(),
        pageSize: (props['pageSize'] as int?) ?? 25,
      );

  @override
  State<DataTable> createState() => _DataTableState();
}

class _Column {
  final String key;
  final String label;
  final bool sortable;

  const _Column({required this.key, required this.label, this.sortable = false});

  factory _Column.fromMap(Map<String, dynamic> raw) => _Column(
        key: raw['key'] as String,
        label: raw['label'] as String,
        sortable: (raw['sortable'] as bool?) ?? false,
      );
}

class _DataTableState extends State<DataTable> {
  String? _sortKey;
  bool _sortAsc = true;
  int _page = 0;

  List<Map<String, dynamic>> get _sortedRows {
    final key = _sortKey;
    if (key == null) return widget.rows;
    final out = List<Map<String, dynamic>>.from(widget.rows);
    out.sort((a, b) {
      final av = a[key];
      final bv = b[key];
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av is Comparable && bv is Comparable) {
        final cmp = av.compareTo(bv);
        return _sortAsc ? cmp : -cmp;
      }
      return 0;
    });
    return out;
  }

  int get _totalPages =>
      (_sortedRows.length / widget.pageSize).ceil().clamp(1, 1 << 30);

  List<Map<String, dynamic>> get _pagedRows => _sortedRows
      .skip(_page * widget.pageSize)
      .take(widget.pageSize)
      .toList(growable: false);

  void _toggleSort(_Column column) {
    if (!column.sortable) return;
    setState(() {
      if (_sortKey == column.key) {
        _sortAsc = !_sortAsc;
      } else {
        _sortKey = column.key;
        _sortAsc = true;
      }
    });
  }

  String _formatCell(dynamic value) {
    if (value == null) return '';
    if (value is String) return value;
    if (value is num || value is bool) return value.toString();
    return jsonEncode(value);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = _pagedRows;

    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Table(
              defaultVerticalAlignment: TableCellVerticalAlignment.middle,
              border: TableBorder(
                horizontalInside: BorderSide(color: theme.colorScheme.outlineVariant),
              ),
              children: [
                TableRow(
                  decoration: BoxDecoration(
                    color: theme.colorScheme.surfaceContainerHighest,
                  ),
                  children: [
                    for (final col in widget.columns)
                      _HeaderCell(
                        column: col,
                        sortKey: _sortKey,
                        sortAsc: _sortAsc,
                        onTap: () => _toggleSort(col),
                      ),
                  ],
                ),
                for (final row in rows)
                  TableRow(
                    children: [
                      for (final col in widget.columns)
                        Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 8,
                          ),
                          child: Text(_formatCell(row[col.key])),
                        ),
                    ],
                  ),
              ],
            ),
          ),
          if (rows.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 32),
              child: Center(
                child: Text('No rows.', style: theme.textTheme.bodyMedium),
              ),
            ),
          if (_totalPages > 1)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest,
                border: Border(
                  top: BorderSide(color: theme.colorScheme.outlineVariant),
                ),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  TextButton(
                    onPressed: _page == 0 ? null : () => setState(() => _page--),
                    child: const Text('← Prev'),
                  ),
                  Text('Page ${_page + 1} / $_totalPages'),
                  TextButton(
                    onPressed: _page >= _totalPages - 1
                        ? null
                        : () => setState(() => _page++),
                    child: const Text('Next →'),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _HeaderCell extends StatelessWidget {
  final _Column column;
  final String? sortKey;
  final bool sortAsc;
  final VoidCallback onTap;

  const _HeaderCell({
    required this.column,
    required this.sortKey,
    required this.sortAsc,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isActive = sortKey == column.key;
    final indicator = !column.sortable
        ? null
        : isActive
            ? (sortAsc ? '▲' : '▼')
            : '↕';
    return InkWell(
      onTap: column.sortable ? onTap : null,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(
          children: [
            Text(
              column.label,
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
            if (indicator != null) ...[
              const SizedBox(width: 4),
              Text(
                indicator,
                style: TextStyle(
                  fontSize: 11,
                  color: isActive
                      ? theme.colorScheme.primary
                      : theme.colorScheme.outline,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

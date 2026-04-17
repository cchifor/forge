import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

class FileExplorerActivity extends StatelessWidget {
  const FileExplorerActivity({super.key, required this.activity, this.onAction});

  final WorkspaceActivity activity;
  final void Function(WorkspaceAction action)? onAction;

  List<Map<String, dynamic>> get _files {
    final raw = activity.content['files'];
    if (raw is List) {
      return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return const [];
  }

  IconData _iconFor(String name, String? type) {
    final ext = name.split('.').last.toLowerCase();
    if (type == 'image' || ['png', 'jpg', 'jpeg', 'gif', 'svg'].contains(ext)) {
      return Icons.image_outlined;
    }
    if (type == 'video' || ['mp4', 'mov', 'webm'].contains(ext)) {
      return Icons.movie_outlined;
    }
    if (type == 'audio' || ['mp3', 'wav'].contains(ext)) {
      return Icons.audiotrack_outlined;
    }
    if (type == 'code' || ['ts', 'js', 'dart', 'py', 'rs'].contains(ext)) {
      return Icons.code;
    }
    if (['md', 'txt', 'csv'].contains(ext)) return Icons.description_outlined;
    return Icons.insert_drive_file_outlined;
  }

  String _fmtSize(int? bytes) {
    if (bytes == null) return '';
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';
  }

  @override
  Widget build(BuildContext context) {
    final files = _files;
    final description = activity.content['description']?.toString();

    return ListView(
      key: const ValueKey('file-explorer'),
      padding: const EdgeInsets.all(12),
      children: [
        if (description != null && description.isNotEmpty) ...[
          Text(description, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 8),
        ],
        if (files.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Center(child: Text('No files available.')),
          )
        else
          ...files.map((file) {
            final name = file['name']?.toString() ?? '';
            final path = file['path']?.toString() ?? '';
            final size = (file['size'] as num?)?.toInt();
            final type = file['type']?.toString();
            return ListTile(
              dense: true,
              leading: Icon(_iconFor(name, type), size: 18),
              title: Text(name, maxLines: 1, overflow: TextOverflow.ellipsis),
              trailing: size != null ? Text(_fmtSize(size)) : null,
              onTap: () => onAction?.call(
                WorkspaceAction(type: 'select_file', data: {'path': path}),
              ),
            );
          }),
      ],
    );
  }
}

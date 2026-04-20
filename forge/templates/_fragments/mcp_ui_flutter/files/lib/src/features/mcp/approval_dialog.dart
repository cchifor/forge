// Approval dialog for MCP tool calls (Flutter scaffold, Phase 3.4).
//
// Use via showDialog(...) and await the resolved approval choice:
//
//   final approved = await showDialog<ApprovalResult>(
//     context: context,
//     builder: (_) => ApprovalDialog(
//       toolName: 'read_file',
//       server: 'filesystem',
//       inputPreview: jsonEncode(input),
//       defaultMode: 'prompt-once',
//     ),
//   );
//   if (approved?.approved == true) { ... }

import 'package:flutter/material.dart';

class ApprovalResult {
  final bool approved;
  final bool remember;

  const ApprovalResult({required this.approved, required this.remember});
}

class ApprovalDialog extends StatefulWidget {
  final String toolName;
  final String server;
  final String inputPreview;
  final String defaultMode;

  const ApprovalDialog({
    super.key,
    required this.toolName,
    required this.server,
    required this.inputPreview,
    required this.defaultMode,
  });

  @override
  State<ApprovalDialog> createState() => _ApprovalDialogState();
}

class _ApprovalDialogState extends State<ApprovalDialog> {
  late bool _remember;

  @override
  void initState() {
    super.initState();
    _remember = widget.defaultMode != 'prompt-every';
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Approve tool call?'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${widget.server} · ${widget.toolName}',
              style: const TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(4),
            ),
            constraints: const BoxConstraints(maxHeight: 200),
            child: SingleChildScrollView(
              child: Text(
                widget.inputPreview,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
              ),
            ),
          ),
          const SizedBox(height: 8),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            dense: true,
            title: const Text('Remember this choice for this session'),
            value: _remember,
            onChanged: (v) => setState(() => _remember = v ?? false),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(
            const ApprovalResult(approved: false, remember: false),
          ),
          child: const Text('Deny'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(
            ApprovalResult(approved: true, remember: _remember),
          ),
          child: const Text('Approve'),
        ),
      ],
    );
  }
}

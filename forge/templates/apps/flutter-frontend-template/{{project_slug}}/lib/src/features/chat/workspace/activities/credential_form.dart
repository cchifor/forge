import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

class CredentialFormActivity extends StatefulWidget {
  const CredentialFormActivity({super.key, required this.activity, this.onAction});

  final WorkspaceActivity activity;
  final void Function(WorkspaceAction action)? onAction;

  @override
  State<CredentialFormActivity> createState() => _CredentialFormActivityState();
}

class _CredentialFormActivityState extends State<CredentialFormActivity> {
  final _formKey = GlobalKey<FormState>();
  final Map<String, TextEditingController> _controllers = {};

  List<Map<String, dynamic>> get _fields {
    final raw = widget.activity.content['fields'];
    if (raw is List) {
      return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return const [];
  }

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  TextEditingController _controllerFor(String name) =>
      _controllers.putIfAbsent(name, () => TextEditingController());

  bool _isPassword(String? type) => type == 'password';

  void _submit() {
    if (_formKey.currentState?.validate() != true) return;
    final values = {
      for (final entry in _controllers.entries) entry.key: entry.value.text,
    };
    widget.onAction?.call(WorkspaceAction(type: 'submit', data: values));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title =
        widget.activity.content['title']?.toString() ?? 'Provide credentials';
    final description = widget.activity.content['description']?.toString();

    return Padding(
      key: const ValueKey('credential-form'),
      padding: const EdgeInsets.all(16),
      child: Form(
        key: _formKey,
        child: ListView(
          children: [
            Text(title, style: theme.textTheme.titleSmall),
            if (description != null && description.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(description, style: theme.textTheme.bodySmall),
            ],
            const SizedBox(height: 12),
            for (final field in _fields) ...[
              TextFormField(
                controller: _controllerFor(field['name']?.toString() ?? ''),
                obscureText: _isPassword(field['type']?.toString()),
                decoration: InputDecoration(
                  labelText: (field['label'] ?? field['name'])?.toString(),
                  hintText: field['placeholder']?.toString(),
                  border: const OutlineInputBorder(),
                ),
                validator: (v) {
                  if (field['required'] == true && (v == null || v.isEmpty)) {
                    return 'Required';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 8),
            ],
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton(onPressed: _submit, child: const Text('Submit')),
            ),
          ],
        ),
      ),
    );
  }
}

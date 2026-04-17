import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

class DynamicFormActivity extends StatefulWidget {
  const DynamicFormActivity({super.key, required this.activity, this.onAction});

  final WorkspaceActivity activity;
  final void Function(WorkspaceAction)? onAction;

  @override
  State<DynamicFormActivity> createState() => _DynamicFormActivityState();
}

class _DynamicFormActivityState extends State<DynamicFormActivity> {
  final _formKey = GlobalKey<FormState>();
  final Map<String, TextEditingController> _text = {};
  final Map<String, bool> _bool = {};
  final Map<String, String?> _select = {};

  List<Map<String, dynamic>> get _fields {
    final raw = widget.activity.content['fields'];
    if (raw is List) {
      return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return const [];
  }

  @override
  void initState() {
    super.initState();
    for (final f in _fields) {
      final name = f['name']?.toString() ?? '';
      final type = f['type']?.toString();
      if (type == 'boolean') {
        _bool[name] = (f['default'] as bool?) ?? false;
      } else if (type == 'select') {
        _select[name] = f['default']?.toString();
      } else {
        _text[name] = TextEditingController(text: f['default']?.toString() ?? '');
      }
    }
  }

  @override
  void dispose() {
    for (final c in _text.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _submit() {
    if (_formKey.currentState?.validate() != true) return;
    final values = <String, dynamic>{
      for (final e in _text.entries) e.key: e.value.text,
      for (final e in _bool.entries) e.key: e.value,
      for (final e in _select.entries) e.key: e.value,
    };
    widget.onAction?.call(WorkspaceAction(type: 'submit', data: values));
  }

  Widget _buildField(Map<String, dynamic> field) {
    final name = field['name']?.toString() ?? '';
    final label = (field['label'] ?? field['name'])?.toString() ?? '';
    final type = field['type']?.toString();
    final required = field['required'] == true;

    if (type == 'boolean') {
      return CheckboxListTile(
        title: Text(label),
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        value: _bool[name] ?? false,
        onChanged: (v) => setState(() => _bool[name] = v ?? false),
      );
    }

    if (type == 'select') {
      final options = (field['options'] as List?)
              ?.whereType<Map>()
              .map((e) => Map<String, dynamic>.from(e))
              .toList() ??
          const [];
      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: DropdownButtonFormField<String>(
          initialValue: _select[name],
          decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
          items: [
            for (final opt in options)
              DropdownMenuItem(
                value: opt['value']?.toString() ?? '',
                child: Text(opt['label']?.toString() ?? ''),
              ),
          ],
          onChanged: (v) => setState(() => _select[name] = v),
          validator: (v) => required && (v == null || v.isEmpty) ? 'Required' : null,
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: TextFormField(
        controller: _text[name],
        maxLines: type == 'textarea' ? 3 : 1,
        keyboardType: type == 'number' ? TextInputType.number : TextInputType.text,
        decoration: InputDecoration(
          labelText: label,
          hintText: field['placeholder']?.toString(),
          border: const OutlineInputBorder(),
        ),
        validator: (v) => required && (v == null || v.isEmpty) ? 'Required' : null,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final title = widget.activity.content['title']?.toString() ?? 'Form';
    return Padding(
      key: const ValueKey('dynamic-form'),
      padding: const EdgeInsets.all(16),
      child: Form(
        key: _formKey,
        child: ListView(
          children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 12),
            ..._fields.map(_buildField),
            const SizedBox(height: 4),
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

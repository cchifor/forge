import 'package:flutter/material.dart';

/// DynamicForm canvas component — renders a form from a JSON-Schema-
/// like field list. Dispatches by type: text, number, password, email,
/// select, checkbox, textarea.
///
/// Props schema:
/// forge/templates/_shared/canvas-components/DynamicForm.props.schema.json
class DynamicForm extends StatefulWidget {
  final String? title;
  final List<_Field> fields;
  final String submitLabel;
  final String cancelLabel;
  final void Function(Map<String, dynamic> values)? onSubmit;
  final VoidCallback? onCancel;

  DynamicForm({
    super.key,
    this.title,
    required List<Map<String, dynamic>> fields,
    this.submitLabel = 'Submit',
    this.cancelLabel = 'Cancel',
    this.onSubmit,
    this.onCancel,
  }) : fields = fields.map(_Field.fromMap).toList(growable: false);

  factory DynamicForm.fromProps(Map<String, dynamic> props) => DynamicForm(
        title: props['title'] as String?,
        fields: ((props['fields'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .toList(),
        submitLabel: (props['submitLabel'] as String?) ?? 'Submit',
        cancelLabel: (props['cancelLabel'] as String?) ?? 'Cancel',
      );

  @override
  State<DynamicForm> createState() => _DynamicFormState();
}

class _Field {
  final String name;
  final String label;
  final String type;
  final bool required;
  final dynamic defaultValue;
  final List<String> options;
  final String? description;

  const _Field({
    required this.name,
    required this.label,
    required this.type,
    required this.required,
    required this.defaultValue,
    required this.options,
    required this.description,
  });

  factory _Field.fromMap(Map<String, dynamic> raw) => _Field(
        name: raw['name'] as String,
        label: raw['label'] as String,
        type: raw['type'] as String,
        required: (raw['required'] as bool?) ?? false,
        defaultValue: raw['default'],
        options: ((raw['options'] as List?) ?? const []).whereType<String>().toList(),
        description: raw['description'] as String?,
      );
}

class _DynamicFormState extends State<DynamicForm> {
  final Map<String, dynamic> _values = {};
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();

  @override
  void initState() {
    super.initState();
    for (final f in widget.fields) {
      _values[f.name] = f.defaultValue ?? _defaultFor(f.type);
    }
  }

  dynamic _defaultFor(String type) {
    if (type == 'checkbox') return false;
    if (type == 'number') return 0;
    return '';
  }

  void _handleSubmit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    widget.onSubmit?.call(Map<String, dynamic>.from(_values));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (widget.title != null && widget.title!.isNotEmpty) ...[
                Text(widget.title!, style: theme.textTheme.titleMedium),
                const SizedBox(height: 12),
              ],
              for (final field in widget.fields) ...[
                _FieldWidget(
                  field: field,
                  initialValue: _values[field.name],
                  onChanged: (v) => _values[field.name] = v,
                ),
                const SizedBox(height: 12),
              ],
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: widget.onCancel,
                    child: Text(widget.cancelLabel),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: _handleSubmit,
                    child: Text(widget.submitLabel),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _FieldWidget extends StatefulWidget {
  final _Field field;
  final dynamic initialValue;
  final void Function(dynamic) onChanged;

  const _FieldWidget({
    required this.field,
    required this.initialValue,
    required this.onChanged,
  });

  @override
  State<_FieldWidget> createState() => _FieldWidgetState();
}

class _FieldWidgetState extends State<_FieldWidget> {
  late TextEditingController _controller;
  late dynamic _value;

  @override
  void initState() {
    super.initState();
    _value = widget.initialValue;
    _controller = TextEditingController(text: _value?.toString() ?? '');
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  String? _validator(String? v) {
    if (widget.field.required && (v == null || v.isEmpty)) {
      return 'Required';
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final field = widget.field;
    final label = field.required ? '${field.label} *' : field.label;
    final decoration = InputDecoration(
      labelText: label,
      helperText: field.type == 'checkbox' ? null : field.description,
      border: const OutlineInputBorder(),
    );

    if (field.type == 'checkbox') {
      return CheckboxListTile(
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        title: Text(field.description ?? field.label),
        value: (_value as bool?) ?? false,
        onChanged: (v) {
          setState(() => _value = v ?? false);
          widget.onChanged(_value);
        },
      );
    }

    if (field.type == 'select') {
      return DropdownButtonFormField<String>(
        decoration: decoration,
        value: _value as String?,
        items: [
          for (final opt in field.options)
            DropdownMenuItem(value: opt, child: Text(opt)),
        ],
        onChanged: (v) {
          setState(() => _value = v);
          widget.onChanged(_value);
        },
        validator: field.required
            ? (v) => v == null || v.isEmpty ? 'Required' : null
            : null,
      );
    }

    TextInputType keyboardType = TextInputType.text;
    bool obscure = false;
    if (field.type == 'number') keyboardType = TextInputType.number;
    if (field.type == 'email') keyboardType = TextInputType.emailAddress;
    if (field.type == 'password') obscure = true;

    return TextFormField(
      controller: _controller,
      decoration: decoration,
      keyboardType: keyboardType,
      obscureText: obscure,
      maxLines: field.type == 'textarea' ? 4 : 1,
      validator: _validator,
      onChanged: (v) {
        if (field.type == 'number') {
          _value = num.tryParse(v) ?? 0;
        } else {
          _value = v;
        }
        widget.onChanged(_value);
      },
    );
  }
}

enum ToolCallStatus { running, completed, error }

/// Client-side tool-call record.
///
/// The wire shape (``id``/``name``/``status``/``args``) mirrors the
/// UI-protocol ``ToolCallInfo`` schema. The two trailing fields are
/// client-only state for Pillar G.2 args-streaming:
///
/// - [argsBuffer] — raw delta accumulator. Every ``TOOL_CALL_ARGS``
///   event appends ``event.delta`` so the UI can show the partial
///   JSON live (newlines stripped) before the (potentially slow) tool
///   returns.
/// - [argsPretty] — set on ``TOOL_CALL_END``. Pretty-printed
///   ``JsonEncoder.withIndent('  ').convert(jsonDecode(argsBuffer))``
///   on success; falls back to the raw buffer on parse error so the
///   user always sees *something* for debugging.
///
/// Field names mirror Vue + Svelte's ``ToolCallInfo`` so the contract
/// test at ``tests/test_chat_tool_call_args_contract.py`` finds a
/// consistent surface across all three stacks.
class ToolCallInfo {
  const ToolCallInfo({
    required this.id,
    required this.name,
    required this.status,
    this.args,
    this.argsBuffer,
    this.argsPretty,
  });

  ToolCallInfo copyWith({
    ToolCallStatus? status,
    Map<String, dynamic>? args,
    String? argsBuffer,
    String? argsPretty,
  }) =>
      ToolCallInfo(
        id: id,
        name: name,
        status: status ?? this.status,
        args: args ?? this.args,
        argsBuffer: argsBuffer ?? this.argsBuffer,
        argsPretty: argsPretty ?? this.argsPretty,
      );

  final String id;
  final String name;
  final ToolCallStatus status;
  final Map<String, dynamic>? args;

  /// Raw delta accumulator — appended on every TOOL_CALL_ARGS event.
  final String? argsBuffer;

  /// Pretty-printed JSON set on TOOL_CALL_END; falls back to raw on
  /// parse error.
  final String? argsPretty;
}

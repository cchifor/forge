enum ToolCallStatus { running, completed, error }

class ToolCallInfo {
  const ToolCallInfo({
    required this.id,
    required this.name,
    required this.status,
    this.args,
  });

  ToolCallInfo copyWith({ToolCallStatus? status, Map<String, dynamic>? args}) =>
      ToolCallInfo(
        id: id,
        name: name,
        status: status ?? this.status,
        args: args ?? this.args,
      );

  final String id;
  final String name;
  final ToolCallStatus status;
  final Map<String, dynamic>? args;
}

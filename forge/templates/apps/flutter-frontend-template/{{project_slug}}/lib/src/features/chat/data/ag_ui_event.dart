/// Typed AG-UI server-sent events.
///
/// We model only the subset the deepagent backend actually emits. Sealed classes
/// (Dart 3) keep the union exhaustive at use-sites without freezed codegen for
/// what is essentially wire-protocol glue.
sealed class AgUiEvent {
  const AgUiEvent();

  /// Parse a single SSE `data:` payload.
  static AgUiEvent? parse(Map<String, dynamic> json) {
    final type = json['type']?.toString();
    if (type == null) return null;
    switch (type) {
      case 'RUN_STARTED':
        return const RunStartedEvent();
      case 'RUN_FINISHED':
        return const RunFinishedEvent();
      case 'RUN_ERROR':
        return RunErrorEvent(message: json['message']?.toString() ?? 'Run failed');
      case 'TEXT_MESSAGE_START':
        return TextMessageStartEvent(
          messageId: json['messageId']?.toString() ?? '',
          role: json['role']?.toString() ?? 'assistant',
        );
      case 'TEXT_MESSAGE_CONTENT':
        return TextMessageContentEvent(
          messageId: json['messageId']?.toString() ?? '',
          delta: json['delta']?.toString() ?? '',
        );
      case 'TEXT_MESSAGE_END':
        return TextMessageEndEvent(
          messageId: json['messageId']?.toString() ?? '',
        );
      case 'MESSAGES_SNAPSHOT':
        final raw = json['messages'];
        return MessagesSnapshotEvent(
          messages: raw is List
              ? raw
                  .whereType<Map>()
                  .map((e) => Map<String, dynamic>.from(e))
                  .toList()
              : const [],
        );
      case 'STATE_SNAPSHOT':
        return StateSnapshotEvent(
          snapshot: json['snapshot'] is Map
              ? Map<String, dynamic>.from(json['snapshot'] as Map)
              : const {},
        );
      case 'STATE_DELTA':
        final raw = json['delta'];
        return StateDeltaEvent(
          delta: raw is List
              ? raw
                  .whereType<Map>()
                  .map((e) => Map<String, dynamic>.from(e))
                  .toList()
              : const [],
        );
      case 'CUSTOM':
        return CustomEvent(
          name: json['name']?.toString() ?? '',
          value: json['value'],
        );
      case 'TOOL_CALL_START':
        return ToolCallStartEvent(
          toolCallId: json['toolCallId']?.toString() ?? '',
          toolCallName: json['toolCallName']?.toString() ?? '',
        );
      case 'TOOL_CALL_ARGS':
        return ToolCallArgsEvent(
          toolCallId: json['toolCallId']?.toString() ?? '',
          delta: json['delta']?.toString() ?? '',
        );
      case 'TOOL_CALL_END':
        return ToolCallEndEvent(
          toolCallId: json['toolCallId']?.toString() ?? '',
        );
      case 'ACTIVITY_SNAPSHOT':
        return ActivitySnapshotEvent(
          messageId: json['messageId']?.toString() ?? '',
          activityType: json['activityType']?.toString() ?? '',
          content: json['content'] is Map
              ? Map<String, dynamic>.from(json['content'] as Map)
              : const {},
        );
      default:
        return UnknownEvent(type: type, raw: json);
    }
  }
}

class RunStartedEvent extends AgUiEvent {
  const RunStartedEvent();
}

class RunFinishedEvent extends AgUiEvent {
  const RunFinishedEvent();
}

class RunErrorEvent extends AgUiEvent {
  const RunErrorEvent({required this.message});
  final String message;
}

class TextMessageStartEvent extends AgUiEvent {
  const TextMessageStartEvent({required this.messageId, required this.role});
  final String messageId;
  final String role;
}

class TextMessageContentEvent extends AgUiEvent {
  const TextMessageContentEvent({required this.messageId, required this.delta});
  final String messageId;
  final String delta;
}

class TextMessageEndEvent extends AgUiEvent {
  const TextMessageEndEvent({required this.messageId});
  final String messageId;
}

class MessagesSnapshotEvent extends AgUiEvent {
  const MessagesSnapshotEvent({required this.messages});
  final List<Map<String, dynamic>> messages;
}

class StateSnapshotEvent extends AgUiEvent {
  const StateSnapshotEvent({required this.snapshot});
  final Map<String, dynamic> snapshot;
}

class StateDeltaEvent extends AgUiEvent {
  const StateDeltaEvent({required this.delta});
  // RFC 6902 JSON Patch operations.
  final List<Map<String, dynamic>> delta;
}

class CustomEvent extends AgUiEvent {
  const CustomEvent({required this.name, required this.value});
  final String name;
  final dynamic value;
}

class ToolCallStartEvent extends AgUiEvent {
  const ToolCallStartEvent({required this.toolCallId, required this.toolCallName});
  final String toolCallId;
  final String toolCallName;
}

class ToolCallArgsEvent extends AgUiEvent {
  const ToolCallArgsEvent({required this.toolCallId, required this.delta});
  final String toolCallId;
  final String delta;
}

class ToolCallEndEvent extends AgUiEvent {
  const ToolCallEndEvent({required this.toolCallId});
  final String toolCallId;
}

class ActivitySnapshotEvent extends AgUiEvent {
  const ActivitySnapshotEvent({
    required this.messageId,
    required this.activityType,
    required this.content,
  });
  final String messageId;
  final String activityType;
  final Map<String, dynamic> content;
}

class UnknownEvent extends AgUiEvent {
  const UnknownEvent({required this.type, required this.raw});
  final String type;
  final Map<String, dynamic> raw;
}

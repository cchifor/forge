import 'package:freezed_annotation/freezed_annotation.dart';

part 'chat_message.freezed.dart';

/// AG-UI message shape — mirrors `Message` from the JS `@ag-ui/core` package.
///
/// The agent client builds messages incrementally as text-delta events stream
/// in; the UI re-renders the in-progress assistant message each tick.
enum ChatRole { user, assistant, system }

ChatRole chatRoleFromString(String value) {
  switch (value) {
    case 'user':
      return ChatRole.user;
    case 'system':
      return ChatRole.system;
    case 'assistant':
    default:
      return ChatRole.assistant;
  }
}

String chatRoleToString(ChatRole role) {
  switch (role) {
    case ChatRole.user:
      return 'user';
    case ChatRole.system:
      return 'system';
    case ChatRole.assistant:
      return 'assistant';
  }
}

@freezed
abstract class ChatMessage with _$ChatMessage {
  const factory ChatMessage({
    required String id,
    required ChatRole role,
    required String content,
    @Default(false) bool isStreaming,
  }) = _ChatMessage;

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        id: json['id']?.toString() ?? '',
        role: chatRoleFromString(json['role']?.toString() ?? 'assistant'),
        content: json['content']?.toString() ?? '',
      );
}

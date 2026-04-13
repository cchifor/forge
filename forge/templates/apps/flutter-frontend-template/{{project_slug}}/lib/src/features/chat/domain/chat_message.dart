import 'package:freezed_annotation/freezed_annotation.dart';

part 'chat_message.freezed.dart';

enum ChatRole { user, assistant }

@freezed
abstract class ChatMessage with _$ChatMessage {
  const factory ChatMessage({
    required String id,
    required String content,
    required ChatRole role,
    required DateTime timestamp,
    @Default(false) bool isStreaming,
  }) = _ChatMessage;
}

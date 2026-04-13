import 'package:{{project_slug}}/src/features/chat/domain/chat_message.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('ChatRole', () {
    test('has user and assistant values', () {
      expect(ChatRole.values, containsAll([ChatRole.user, ChatRole.assistant]));
      expect(ChatRole.values, hasLength(2));
    });
  });

  group('ChatMessage', () {
    final now = DateTime(2026, 1, 15, 10, 30);

    test('creates with required fields and defaults', () {
      final msg = ChatMessage(
        id: 'msg-1',
        content: 'Hello',
        role: ChatRole.user,
        timestamp: now,
      );
      expect(msg.id, 'msg-1');
      expect(msg.content, 'Hello');
      expect(msg.role, ChatRole.user);
      expect(msg.timestamp, now);
      expect(msg.isStreaming, isFalse);
    });

    test('isStreaming can be set to true', () {
      final msg = ChatMessage(
        id: 'msg-2',
        content: '',
        role: ChatRole.assistant,
        timestamp: now,
        isStreaming: true,
      );
      expect(msg.isStreaming, isTrue);
    });

    test('two messages with same fields are equal', () {
      final a = ChatMessage(
        id: 'msg-1',
        content: 'Hi',
        role: ChatRole.user,
        timestamp: now,
      );
      final b = ChatMessage(
        id: 'msg-1',
        content: 'Hi',
        role: ChatRole.user,
        timestamp: now,
      );
      expect(a, equals(b));
    });

    test('messages with different ids are not equal', () {
      final a = ChatMessage(
        id: 'msg-1',
        content: 'Hi',
        role: ChatRole.user,
        timestamp: now,
      );
      final b = ChatMessage(
        id: 'msg-2',
        content: 'Hi',
        role: ChatRole.user,
        timestamp: now,
      );
      expect(a, isNot(equals(b)));
    });
  });
}

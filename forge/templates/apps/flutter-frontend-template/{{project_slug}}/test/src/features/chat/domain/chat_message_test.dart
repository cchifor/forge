import 'package:{{project_slug}}/src/features/chat/domain/chat_message.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('ChatRole', () {
    test('has user/assistant/system values', () {
      expect(
        ChatRole.values,
        containsAll([ChatRole.user, ChatRole.assistant, ChatRole.system]),
      );
    });

    test('chatRoleFromString round-trips', () {
      for (final role in ChatRole.values) {
        expect(chatRoleFromString(chatRoleToString(role)), role);
      }
    });

    test('chatRoleFromString defaults to assistant for unknown input', () {
      expect(chatRoleFromString('weird'), ChatRole.assistant);
    });
  });

  group('ChatMessage', () {
    test('creates with required fields and isStreaming defaults to false', () {
      const msg = ChatMessage(
        id: 'msg-1',
        role: ChatRole.user,
        content: 'Hello',
      );
      expect(msg.id, 'msg-1');
      expect(msg.content, 'Hello');
      expect(msg.role, ChatRole.user);
      expect(msg.isStreaming, isFalse);
    });

    test('isStreaming can be set to true (in-progress assistant message)', () {
      const msg = ChatMessage(
        id: 'msg-2',
        role: ChatRole.assistant,
        content: '',
        isStreaming: true,
      );
      expect(msg.isStreaming, isTrue);
    });

    test('two messages with same fields are equal (freezed)', () {
      const a = ChatMessage(id: 'msg-1', role: ChatRole.user, content: 'Hi');
      const b = ChatMessage(id: 'msg-1', role: ChatRole.user, content: 'Hi');
      expect(a, equals(b));
    });

    test('fromJson parses minimal payload', () {
      final msg = ChatMessage.fromJson({
        'id': 'x',
        'role': 'user',
        'content': 'hi',
      });
      expect(msg.id, 'x');
      expect(msg.role, ChatRole.user);
      expect(msg.content, 'hi');
    });
  });
}

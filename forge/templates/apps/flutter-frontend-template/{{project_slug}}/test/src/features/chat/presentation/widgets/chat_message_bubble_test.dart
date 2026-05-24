import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:{{project_slug}}/src/features/chat/domain/chat_message.dart';
import 'package:{{project_slug}}/src/features/chat/presentation/widgets/chat_message_bubble.dart';

/// Token-streaming debounce contract: rapid TEXT_MESSAGE_CONTENT deltas must
/// collapse into a single deferred render, but the final tokens (delivered
/// when ``isStreaming`` flips to false at TEXT_MESSAGE_END) must appear
/// within the next frame regardless of where the debounce timer was.
void main() {
  String renderedMarkdown(WidgetTester tester) {
    final body = tester.widget<MarkdownBody>(find.byType(MarkdownBody));
    return body.data;
  }

  Future<void> pumpBubble(WidgetTester tester, ChatMessage message) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ChatMessageBubble(message: message),
        ),
      ),
    );
  }

  testWidgets(
    '10 rapid token updates within 50ms produce <= 2 markdown rebuilds',
    (tester) async {
      // Initial mount with the first streamed token.
      await pumpBubble(
        tester,
        const ChatMessage(
          id: 'm1',
          role: ChatRole.assistant,
          content: 'a',
          isStreaming: true,
        ),
      );
      // Sanity: the first content is rendered.
      expect(renderedMarkdown(tester), 'a');

      // 10 deltas at 5ms intervals — all inside the 50ms debounce window.
      final renderedSnapshots = <String>{};
      var content = 'a';
      for (var i = 0; i < 10; i++) {
        content += 'b';
        await pumpBubble(
          tester,
          ChatMessage(
            id: 'm1',
            role: ChatRole.assistant,
            content: content,
            isStreaming: true,
          ),
        );
        await tester.pump(const Duration(milliseconds: 5));
        renderedSnapshots.add(renderedMarkdown(tester));
      }

      // During the burst, the visible markdown should not have advanced past
      // the first cached value — every delta is dropped pending the timer.
      // (Initial render counts as 1; we accept <= 2 unique values to allow
      // for early flushes if the platform clock skews.)
      expect(renderedSnapshots.length, lessThanOrEqualTo(2));

      // Close the debounce window — one deferred render fires.
      await tester.pump(const Duration(milliseconds: 50));
      expect(renderedMarkdown(tester), content);
    },
  );

  testWidgets(
    'flushes the final tokens immediately when isStreaming flips to false',
    (tester) async {
      await pumpBubble(
        tester,
        const ChatMessage(
          id: 'm1',
          role: ChatRole.assistant,
          content: 'partial',
          isStreaming: true,
        ),
      );
      expect(renderedMarkdown(tester), 'partial');

      // New token arrives — debounce timer pending.
      await pumpBubble(
        tester,
        const ChatMessage(
          id: 'm1',
          role: ChatRole.assistant,
          content: 'partial + final',
          isStreaming: true,
        ),
      );
      // Do NOT advance time. Stream ends now.
      await pumpBubble(
        tester,
        const ChatMessage(
          id: 'm1',
          role: ChatRole.assistant,
          content: 'partial + final',
          isStreaming: false,
        ),
      );

      // Final content must be visible within the same frame as END — not
      // delayed by the (still-pending) debounce timer.
      expect(renderedMarkdown(tester), 'partial + final');
    },
  );

  testWidgets('non-streaming updates render synchronously (no debounce)', (
    tester,
  ) async {
    await pumpBubble(
      tester,
      const ChatMessage(
        id: 'm1',
        role: ChatRole.assistant,
        content: 'first',
      ),
    );
    expect(renderedMarkdown(tester), 'first');

    await pumpBubble(
      tester,
      const ChatMessage(
        id: 'm1',
        role: ChatRole.assistant,
        content: 'second',
      ),
    );
    expect(renderedMarkdown(tester), 'second');
  });
}

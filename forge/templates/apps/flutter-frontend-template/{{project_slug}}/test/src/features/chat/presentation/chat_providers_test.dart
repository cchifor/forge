import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:forge_canvas/forge_canvas.dart' as fc;
import 'package:mocktail/mocktail.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:{{project_slug}}/src/features/chat/data/ag_ui_event.dart';
import 'package:{{project_slug}}/src/features/chat/domain/chat_message.dart';
import 'package:{{project_slug}}/src/features/chat/presentation/chat_providers.dart';

class MockAgUiClient extends Mock implements fc.AgUiClient<AgUiEvent> {}

void main() {
  setUpAll(() {
    SharedPreferences.setMockInitialValues({});
  });

  late MockAgUiClient mockClient;
  late ProviderContainer container;

  setUp(() {
    mockClient = MockAgUiClient();
    container = ProviderContainer(
      overrides: [
        agUiClientProvider.overrideWithValue(mockClient),
      ],
    );
  });

  tearDown(() => container.dispose());

  Stream<AgUiEvent> emptyStream() => Stream<AgUiEvent>.fromIterable(const []);

  Stream<AgUiEvent> errorStream(String message) =>
      Stream<AgUiEvent>.fromIterable([RunErrorEvent(message: message)]);

  group('ChatNotifier.retryLastRun', () {
    test('is a no-op before any sendMessage', () async {
      final notifier = container.read(chatProvider.notifier);
      await notifier.retryLastRun();
      verifyNever(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          ));
    });

    test('re-invokes runAgent with the same forwardedProps + thread', () async {
      when(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).thenAnswer((_) => emptyStream());

      final notifier = container.read(chatProvider.notifier);
      await notifier.sendMessage(
        'hello',
        bearerToken: 'tok-xyz',
        attachmentIds: const ['file-1', 'file-2'],
      );

      final firstCall = verify(() => mockClient.runAgent(
            threadId: captureAny(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: captureAny(named: 'forwardedProps'),
            bearerToken: captureAny(named: 'bearerToken'),
          )).captured;
      final firstThreadId = firstCall[0] as String;
      final firstProps = firstCall[1] as Map<String, dynamic>;
      final firstToken = firstCall[2] as String?;

      expect(firstProps['model'], isNotNull);
      expect(firstProps['approval'], isNotNull);
      expect(firstProps['attachment_ids'], equals(['file-1', 'file-2']));
      expect(firstToken, 'tok-xyz');

      await notifier.retryLastRun();

      final retryCall = verify(() => mockClient.runAgent(
            threadId: captureAny(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: captureAny(named: 'forwardedProps'),
            bearerToken: captureAny(named: 'bearerToken'),
          )).captured;
      final retryThreadId = retryCall[0] as String;
      final retryProps = retryCall[1] as Map<String, dynamic>;
      final retryToken = retryCall[2] as String?;

      // Thread context preserved — retry MUST stay on the same conversation.
      expect(retryThreadId, firstThreadId);
      // Same model + approval + attachments forwarded.
      expect(retryProps['attachment_ids'], equals(['file-1', 'file-2']));
      expect(retryProps['model'], firstProps['model']);
      expect(retryProps['approval'], firstProps['approval']);
      expect(retryToken, 'tok-xyz');
    });

    test('does not retry while a run is in flight', () async {
      final completer = Completer<void>();
      final controller = StreamController<AgUiEvent>();
      when(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).thenAnswer((_) => controller.stream);

      final notifier = container.read(chatProvider.notifier);
      // Fire-and-forget so the run is still "in flight" when we call retry.
      final sendFuture = notifier.sendMessage('hello');
      // Yield to let `_runAgent` set isRunning=true before we probe it.
      await Future<void>.delayed(Duration.zero);
      expect(container.read(chatIsRunningProvider), isTrue);

      await notifier.retryLastRun();
      // Only the original sendMessage invocation should have hit the client.
      verify(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).called(1);

      await controller.close();
      await sendFuture;
      completer.complete();
    });
  });

  group('ChatNotifier.regenerate', () {
    test('truncates from messageId onward and preserves the threadId', () async {
      // First turn: a normal sendMessage produces a user msg + we
      // simulate the agent streaming back an assistant msg via the
      // reducer (TextMessageStart + TextMessageEnd).
      when(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).thenAnswer((_) => Stream<AgUiEvent>.fromIterable([
            const TextMessageStartEvent(messageId: 'asst-1', role: 'assistant'),
            const TextMessageContentEvent(messageId: 'asst-1', delta: 'hello'),
            const TextMessageEndEvent(messageId: 'asst-1'),
          ]));

      final notifier = container.read(chatProvider.notifier);
      await notifier.sendMessage('hi', bearerToken: 'tok-1');

      // Capture the threadId from the first call.
      final firstCall = verify(() => mockClient.runAgent(
            threadId: captureAny(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).captured;
      final firstThreadId = firstCall[0] as String;

      // Sanity: the user msg + streamed assistant msg are both there.
      final after = container.read(chatMessagesProvider);
      expect(after, hasLength(2));
      expect(after.last.id, 'asst-1');

      // Now regenerate from the assistant message.
      when(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).thenAnswer((_) => Stream<AgUiEvent>.fromIterable(const []));
      await notifier.regenerate('asst-1');

      // The assistant message is truncated; user msg remains.
      final afterRegen = container.read(chatMessagesProvider);
      expect(afterRegen, hasLength(1));
      expect(afterRegen.single.role, ChatRole.user);

      // The regenerate call MUST hit the agent on the SAME thread.
      final regenCall = verify(() => mockClient.runAgent(
            threadId: captureAny(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: captureAny(named: 'forwardedProps'),
            bearerToken: captureAny(named: 'bearerToken'),
          )).captured;
      final regenThreadId = regenCall[0] as String;
      final regenProps = regenCall[1] as Map<String, dynamic>;
      final regenToken = regenCall[2] as String?;

      // ── Load-bearing invariant: regenerate keeps the thread. ──
      expect(regenThreadId, firstThreadId);
      // ── Re-uses lastRunOptions (bearerToken + model + approval). ──
      expect(regenToken, 'tok-1');
      expect(regenProps['model'], isNotNull);
      expect(regenProps['approval'], isNotNull);
    });

    test('is a no-op for unknown messageId', () async {
      when(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).thenAnswer((_) => emptyStream());

      final notifier = container.read(chatProvider.notifier);
      await notifier.sendMessage('hi');
      await notifier.regenerate('nope');

      // Only the original sendMessage hit the client — regenerate
      // bailed before invoking the agent.
      verify(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).called(1);
    });

    test('does not regenerate while a run is in flight', () async {
      // Seed a successful first turn that streams an assistant msg.
      when(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).thenAnswer((_) => Stream<AgUiEvent>.fromIterable([
            const TextMessageStartEvent(messageId: 'asst-2', role: 'assistant'),
            const TextMessageEndEvent(messageId: 'asst-2'),
          ]));
      final notifier = container.read(chatProvider.notifier);
      await notifier.sendMessage('hi');
      expect(container.read(chatMessagesProvider), hasLength(2));

      // Now start a never-completing second run.
      final controller = StreamController<AgUiEvent>();
      when(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).thenAnswer((_) => controller.stream);
      final inflight = notifier.sendMessage('follow up');
      await Future<void>.delayed(Duration.zero);
      expect(container.read(chatIsRunningProvider), isTrue);

      await notifier.regenerate('asst-2');

      // Only sendMessage(1) + sendMessage(2) hit the client — regen
      // bailed on `state.isRunning`.
      verify(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).called(2);

      await controller.close();
      await inflight;
    });

    test('is a no-op when no prior sendMessage has fired (hasRun gate)', () async {
      // Codex Phase B round 1 follow-up. Calling regenerate before
      // any sendMessage has captured `_lastForwardedProps` /
      // `_lastBearerToken` would otherwise fall through to _runAgent
      // with empty forwardedProps, silently dropping model + approval.
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(chatProvider.notifier);
      // Add a user message directly (bypassing sendMessage so
      // _hasRun stays false), then attempt regenerate.
      notifier.state = notifier.state.copyWith(
        messages: const [
          ChatMessage(id: 'msg-1', role: ChatRole.user, content: 'hi'),
        ],
      );
      await notifier.regenerate('msg-1');
      verifyNever(
        () => mockClient.runAgent(
          threadId: any(named: 'threadId'),
          runId: any(named: 'runId'),
          messages: any(named: 'messages'),
          state: any(named: 'state'),
          forwardedProps: any(named: 'forwardedProps'),
          bearerToken: any(named: 'bearerToken'),
        ),
      );
    });
  });

  group('ChatNotifier.dismissError', () {
    test('clears the error without firing a new runAgent', () async {
      when(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).thenAnswer((_) => errorStream('boom'));

      final notifier = container.read(chatProvider.notifier);
      await notifier.sendMessage('hello');
      expect(container.read(chatErrorProvider), 'boom');

      notifier.dismissError();
      expect(container.read(chatErrorProvider), isNull);
      // Only the original send hit the client — dismiss is purely local.
      verify(() => mockClient.runAgent(
            threadId: any(named: 'threadId'),
            runId: any(named: 'runId'),
            messages: any(named: 'messages'),
            state: any(named: 'state'),
            forwardedProps: any(named: 'forwardedProps'),
            bearerToken: any(named: 'bearerToken'),
          )).called(1);
    });

    test('is a no-op when there is no error', () {
      final notifier = container.read(chatProvider.notifier);
      expect(() => notifier.dismissError(), returnsNormally);
      expect(container.read(chatErrorProvider), isNull);
    });
  });
}

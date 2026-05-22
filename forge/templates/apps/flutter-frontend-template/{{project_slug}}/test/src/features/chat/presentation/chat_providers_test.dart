import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:forge_canvas/forge_canvas.dart' as fc;
import 'package:mocktail/mocktail.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:{{project_slug}}/src/features/chat/data/ag_ui_event.dart';
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

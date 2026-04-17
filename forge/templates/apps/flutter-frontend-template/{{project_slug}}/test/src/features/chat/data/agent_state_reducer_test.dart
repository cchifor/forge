import 'package:flutter_test/flutter_test.dart';
import 'package:{{project_slug}}/src/features/chat/data/ag_ui_event.dart';
import 'package:{{project_slug}}/src/features/chat/data/agent_state_reducer.dart';
import 'package:{{project_slug}}/src/features/chat/domain/chat_message.dart';
import 'package:{{project_slug}}/src/features/chat/domain/tool_call_info.dart';

void main() {
  group('reduce', () {
    test('RUN_STARTED flips isRunning and clears error', () {
      const initial = ChatStateSnapshot(error: 'old');
      final next = reduce(initial, const RunStartedEvent());
      expect(next.isRunning, isTrue);
      expect(next.error, isNull);
    });

    test('RUN_FINISHED clears isRunning', () {
      const initial = ChatStateSnapshot(isRunning: true);
      final next = reduce(initial, const RunFinishedEvent());
      expect(next.isRunning, isFalse);
    });

    test('RUN_ERROR captures the message', () {
      const initial = ChatStateSnapshot(isRunning: true);
      final next = reduce(initial, const RunErrorEvent(message: 'oops'));
      expect(next.error, 'oops');
      expect(next.isRunning, isFalse);
    });

    test('TEXT_MESSAGE_START appends a streaming assistant message', () {
      final next = reduce(
        ChatStateSnapshot.empty,
        const TextMessageStartEvent(messageId: 'm1', role: 'assistant'),
      );
      expect(next.messages, hasLength(1));
      expect(next.messages.first.id, 'm1');
      expect(next.messages.first.role, ChatRole.assistant);
      expect(next.messages.first.isStreaming, isTrue);
    });

    test('TEXT_MESSAGE_CONTENT appends deltas to the right message', () {
      var s = reduce(
        ChatStateSnapshot.empty,
        const TextMessageStartEvent(messageId: 'm1', role: 'assistant'),
      );
      s = reduce(s, const TextMessageContentEvent(messageId: 'm1', delta: 'Hel'));
      s = reduce(s, const TextMessageContentEvent(messageId: 'm1', delta: 'lo'));
      expect(s.messages.first.content, 'Hello');
    });

    test('TEXT_MESSAGE_END flips isStreaming false', () {
      var s = reduce(
        ChatStateSnapshot.empty,
        const TextMessageStartEvent(messageId: 'm1', role: 'assistant'),
      );
      s = reduce(s, const TextMessageEndEvent(messageId: 'm1'));
      expect(s.messages.first.isStreaming, isFalse);
    });

    test('TOOL_CALL_START appends and TOOL_CALL_END marks completed', () {
      var s = reduce(
        ChatStateSnapshot.empty,
        const ToolCallStartEvent(toolCallId: 't1', toolCallName: 'fetch_url'),
      );
      expect(s.activeToolCalls, hasLength(1));
      expect(s.activeToolCalls.first.status, ToolCallStatus.running);
      s = reduce(s, const ToolCallEndEvent(toolCallId: 't1'));
      expect(s.activeToolCalls.first.status, ToolCallStatus.completed);
    });

    test('STATE_SNAPSHOT replaces agent state', () {
      final next = reduce(
        ChatStateSnapshot.empty,
        const StateSnapshotEvent(
          snapshot: {
            'cost': {
              'total_usd': 0.42,
              'total_tokens': 100,
              'run_usd': 0.01,
              'run_tokens': 10,
            },
            'todos': [
              {'content': 'Do thing', 'status': 'pending'}
            ],
          },
        ),
      );
      expect(next.agentState.cost?.totalUsd, 0.42);
      expect(next.agentState.todos, hasLength(1));
      expect(next.agentState.todos.first.content, 'Do thing');
    });

    test('STATE_DELTA applies JSON patch to the raw agent map', () {
      var s = reduce(
        ChatStateSnapshot.empty,
        const StateSnapshotEvent(snapshot: {'todos': [], 'count': 0}),
      );
      s = reduce(
        s,
        const StateDeltaEvent(
          delta: [
            {'op': 'replace', 'path': '/count', 'value': 5},
          ],
        ),
      );
      expect(s.rawAgentMap['count'], 5);
    });

    test('CUSTOM deepagent.user_prompt surfaces a pending prompt', () {
      final next = reduce(
        ChatStateSnapshot.empty,
        const CustomEvent(
          name: 'deepagent.user_prompt',
          value: <String, dynamic>{
            'tool_call_id': 'tc1',
            'question': 'Approve?',
            'options': [
              {'label': 'Yes'},
              {'label': 'No'},
            ],
          },
        ),
      );
      expect(next.pendingPrompt?.question, 'Approve?');
      expect(next.pendingPrompt?.options, hasLength(2));
    });

    test('ACTIVITY_SNAPSHOT routes by content.target', () {
      final canvasEvent = const ActivitySnapshotEvent(
        messageId: 'm1',
        activityType: 'dynamic-form',
        content: {'target': 'canvas', 'engine': 'ag-ui'},
      );
      final s = reduce(ChatStateSnapshot.empty, canvasEvent);
      expect(s.canvasActivity, isNotNull);
      expect(s.canvasActivity!.activityType, 'dynamic-form');
      expect(s.workspaceActivity, isNull);
    });
  });
}

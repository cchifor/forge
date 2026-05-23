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
      // No TOOL_CALL_ARGS arrived — argsBuffer/argsPretty stay null so
      // the collapsible just hides in the UI.
      expect(s.activeToolCalls.first.argsBuffer, isNull);
      s = reduce(s, const ToolCallEndEvent(toolCallId: 't1'));
      expect(s.activeToolCalls.first.status, ToolCallStatus.completed);
      expect(s.activeToolCalls.first.argsPretty, isNull);
    });

    // ── TOOL_CALL_ARGS streaming (Pillar G.2) ──

    test('TOOL_CALL_ARGS accumulates delta into argsBuffer', () {
      var s = reduce(
        ChatStateSnapshot.empty,
        const ToolCallStartEvent(toolCallId: 't-a', toolCallName: 'search'),
      );
      s = reduce(s, const ToolCallArgsEvent(toolCallId: 't-a', delta: '{"q":'));
      s = reduce(s, const ToolCallArgsEvent(toolCallId: 't-a', delta: '"hi"}'));
      expect(s.activeToolCalls.first.argsBuffer, '{"q":"hi"}');
      // argsPretty is set only on TOOL_CALL_END.
      expect(s.activeToolCalls.first.argsPretty, isNull);
    });

    test('TOOL_CALL_END pretty-prints argsBuffer via JsonEncoder', () {
      var s = reduce(
        ChatStateSnapshot.empty,
        const ToolCallStartEvent(toolCallId: 't-b', toolCallName: 'search'),
      );
      s = reduce(
        s,
        const ToolCallArgsEvent(toolCallId: 't-b', delta: '{"q":"hi","n":1}'),
      );
      s = reduce(s, const ToolCallEndEvent(toolCallId: 't-b'));
      expect(
        s.activeToolCalls.first.argsPretty,
        '{\n  "q": "hi",\n  "n": 1\n}',
      );
      expect(s.activeToolCalls.first.status, ToolCallStatus.completed);
    });

    test('TOOL_CALL_END falls back to raw buffer on JSON parse error', () {
      var s = reduce(
        ChatStateSnapshot.empty,
        const ToolCallStartEvent(toolCallId: 't-c', toolCallName: 'search'),
      );
      s = reduce(
        s,
        const ToolCallArgsEvent(toolCallId: 't-c', delta: 'not-json{{'),
      );
      s = reduce(s, const ToolCallEndEvent(toolCallId: 't-c'));
      // Parse fails → argsPretty mirrors the raw delta so the user
      // still sees *something* in the collapsible preview.
      expect(s.activeToolCalls.first.argsPretty, 'not-json{{');
    });

    test('concurrent tool calls keep separate argsBuffers', () {
      var s = reduce(
        ChatStateSnapshot.empty,
        const ToolCallStartEvent(toolCallId: 't-x', toolCallName: 'a'),
      );
      s = reduce(
        s,
        const ToolCallStartEvent(toolCallId: 't-y', toolCallName: 'b'),
      );
      s = reduce(s, const ToolCallArgsEvent(toolCallId: 't-x', delta: '{"x":1}'));
      s = reduce(s, const ToolCallArgsEvent(toolCallId: 't-y', delta: '{"y":2}'));
      expect(s.activeToolCalls, hasLength(2));
      final x = s.activeToolCalls.firstWhere((tc) => tc.id == 't-x');
      final y = s.activeToolCalls.firstWhere((tc) => tc.id == 't-y');
      expect(x.argsBuffer, '{"x":1}');
      expect(y.argsBuffer, '{"y":2}');
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

import 'dart:convert';

import 'package:json_patch/json_patch.dart';

import '../domain/agent_state.dart';
import '../domain/chat_message.dart';
import '../domain/tool_call_info.dart';
import '../domain/user_prompt_payload.dart';
import '../domain/workspace_activity.dart';
import 'ag_ui_event.dart';

/// Two-space JSON pretty-printer used by [_prettifyArgs] on
/// ``TOOL_CALL_END``. Mirrors Vue/Svelte's
/// ``JSON.stringify(value, null, 2)``.
const _argsEncoder = JsonEncoder.withIndent('  ');

/// Pretty-print a streamed TOOL_CALL_ARGS buffer for the collapsible
/// preview. Returns ``null`` for empty input so the UI can hide the
/// preview (`argsPretty` stays unset on the model). On JSON parse
/// failure, returns the raw buffer so the user still sees *something*
/// for debugging — cross-stack consistency with Vue + Svelte.
String? _prettifyArgs(String? buffer) {
  if (buffer == null || buffer.isEmpty) return null;
  try {
    return _argsEncoder.convert(jsonDecode(buffer));
  } catch (_) {
    return buffer;
  }
}

/// Snapshot of all chat state the UI needs to render.
///
/// Treated immutably — every reducer step returns a new copy. Held inside a
/// `ChatNotifier` (Riverpod) so widget rebuilds happen on assignment.
class ChatStateSnapshot {
  const ChatStateSnapshot({
    this.messages = const [],
    this.activeToolCalls = const [],
    this.pendingPrompt,
    this.canvasActivity,
    this.workspaceActivity,
    this.agentState = AgentState.empty,
    // Internal — JSON-Patch needs the raw map for round-tripping.
    this.rawAgentMap = const {},
    this.isRunning = false,
    this.error,
  });

  ChatStateSnapshot copyWith({
    List<ChatMessage>? messages,
    List<ToolCallInfo>? activeToolCalls,
    UserPromptPayload? pendingPrompt,
    bool clearPendingPrompt = false,
    WorkspaceActivity? canvasActivity,
    bool clearCanvas = false,
    WorkspaceActivity? workspaceActivity,
    bool clearWorkspace = false,
    AgentState? agentState,
    Map<String, dynamic>? rawAgentMap,
    bool? isRunning,
    String? error,
    bool clearError = false,
  }) {
    return ChatStateSnapshot(
      messages: messages ?? this.messages,
      activeToolCalls: activeToolCalls ?? this.activeToolCalls,
      pendingPrompt:
          clearPendingPrompt ? null : (pendingPrompt ?? this.pendingPrompt),
      canvasActivity:
          clearCanvas ? null : (canvasActivity ?? this.canvasActivity),
      workspaceActivity:
          clearWorkspace ? null : (workspaceActivity ?? this.workspaceActivity),
      agentState: agentState ?? this.agentState,
      rawAgentMap: rawAgentMap ?? this.rawAgentMap,
      isRunning: isRunning ?? this.isRunning,
      error: clearError ? null : (error ?? this.error),
    );
  }

  final List<ChatMessage> messages;
  final List<ToolCallInfo> activeToolCalls;
  final UserPromptPayload? pendingPrompt;
  final WorkspaceActivity? canvasActivity;
  final WorkspaceActivity? workspaceActivity;
  final AgentState agentState;
  final Map<String, dynamic> rawAgentMap;
  final bool isRunning;
  final String? error;

  static const empty = ChatStateSnapshot();
}

/// Pure reducer: `(snapshot, event) -> snapshot`. Side-effect free so it tests
/// without a Riverpod container, a fake Dio, or any timers.
ChatStateSnapshot reduce(ChatStateSnapshot snapshot, AgUiEvent event) {
  switch (event) {
    case RunStartedEvent():
      return snapshot.copyWith(isRunning: true, clearError: true);

    case RunFinishedEvent():
      return snapshot.copyWith(isRunning: false);

    case RunErrorEvent(message: final m):
      return snapshot.copyWith(isRunning: false, error: m);

    case TextMessageStartEvent(messageId: final id, role: final role):
      return snapshot.copyWith(
        messages: [
          ...snapshot.messages,
          ChatMessage(
            id: id,
            role: chatRoleFromString(role),
            content: '',
            isStreaming: true,
          ),
        ],
      );

    case TextMessageContentEvent(messageId: final id, delta: final delta):
      if (snapshot.messages.isEmpty) return snapshot;
      final updated = List<ChatMessage>.from(snapshot.messages);
      final lastIndex = updated.lastIndexWhere((m) => m.id == id);
      final targetIndex = lastIndex >= 0 ? lastIndex : updated.length - 1;
      final target = updated[targetIndex];
      updated[targetIndex] = target.copyWith(content: target.content + delta);
      return snapshot.copyWith(messages: updated);

    case TextMessageEndEvent(messageId: final id):
      final updated = snapshot.messages
          .map((m) => m.id == id ? m.copyWith(isStreaming: false) : m)
          .toList();
      return snapshot.copyWith(messages: updated);

    case MessagesSnapshotEvent(messages: final msgs):
      return snapshot.copyWith(
        messages: msgs.map(ChatMessage.fromJson).toList(),
      );

    case StateSnapshotEvent(snapshot: final raw):
      return snapshot.copyWith(
        agentState: AgentState.fromMap(raw),
        rawAgentMap: Map<String, dynamic>.from(raw),
      );

    case StateDeltaEvent(delta: final patches):
      try {
        final patched = JsonPatch.apply(
          Map<String, dynamic>.from(snapshot.rawAgentMap),
          patches,
        );
        if (patched is! Map<String, dynamic>) return snapshot;
        return snapshot.copyWith(
          agentState: AgentState.fromMap(patched),
          rawAgentMap: patched,
        );
      } catch (_) {
        // Failed patch — keep old state, wait for next snapshot.
        return snapshot;
      }

    case CustomEvent(name: final name, value: final value):
      if (name == 'deepagent.state_snapshot' &&
          value is Map<String, dynamic>) {
        return snapshot.copyWith(
          agentState: AgentState.fromMap(value),
          rawAgentMap: Map<String, dynamic>.from(value),
        );
      }
      if (name == 'deepagent.user_prompt' && value is Map<String, dynamic>) {
        return snapshot.copyWith(
          pendingPrompt: UserPromptPayload.fromJson(value),
        );
      }
      return snapshot;

    case ToolCallStartEvent(toolCallId: final id, toolCallName: final name):
      return snapshot.copyWith(
        activeToolCalls: [
          ...snapshot.activeToolCalls,
          ToolCallInfo(
            id: id,
            name: name,
            status: ToolCallStatus.running,
          ),
        ],
      );

    case ToolCallEndEvent(toolCallId: final id):
      // Pillar G.2: pretty-print the accumulated argsBuffer on END.
      // ``_prettifyArgs`` handles the JSON-parse + fall-back-to-raw
      // dance; returns ``null`` for empty buffers so we don't fabricate
      // an empty preview.
      return snapshot.copyWith(
        activeToolCalls: snapshot.activeToolCalls.map((tc) {
          if (tc.id != id) return tc;
          final pretty = _prettifyArgs(tc.argsBuffer);
          if (pretty == null) {
            return tc.copyWith(status: ToolCallStatus.completed);
          }
          return tc.copyWith(
            status: ToolCallStatus.completed,
            argsPretty: pretty,
          );
        }).toList(),
      );

    case ToolCallArgsEvent(toolCallId: final id, delta: final delta):
      // Pillar G.2: append the delta into the per-tool-call buffer.
      // Keyed on ``toolCallId`` so multiple concurrent tool calls
      // don't cross-contaminate. Pretty-printing happens on END.
      return snapshot.copyWith(
        activeToolCalls: snapshot.activeToolCalls
            .map((tc) => tc.id == id
                ? tc.copyWith(argsBuffer: (tc.argsBuffer ?? '') + delta)
                : tc)
            .toList(),
      );

    case ActivitySnapshotEvent(
        messageId: final mid,
        activityType: final type,
        content: final content,
      ):
      final engine = (content['engine']?.toString() == 'mcp-ext')
          ? AgentEngine.mcpExt
          : AgentEngine.agUi;
      final activity = WorkspaceActivity(
        engine: engine,
        activityType: type,
        messageId: mid,
        content: content,
      );
      if (content['target']?.toString() == 'canvas') {
        return snapshot.copyWith(canvasActivity: activity);
      }
      return snapshot.copyWith(workspaceActivity: activity);

    case UnknownEvent():
      return snapshot;
  }
}

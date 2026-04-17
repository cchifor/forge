import 'package:json_patch/json_patch.dart';

import '../domain/agent_state.dart';
import '../domain/chat_message.dart';
import '../domain/tool_call_info.dart';
import '../domain/user_prompt_payload.dart';
import '../domain/workspace_activity.dart';
import 'ag_ui_event.dart';

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
      return snapshot.copyWith(
        activeToolCalls: snapshot.activeToolCalls
            .map((tc) => tc.id == id
                ? tc.copyWith(status: ToolCallStatus.completed)
                : tc)
            .toList(),
      );

    case ToolCallArgsEvent():
      // Args streaming for live tool-call display — not surfaced in v1.
      return snapshot;

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

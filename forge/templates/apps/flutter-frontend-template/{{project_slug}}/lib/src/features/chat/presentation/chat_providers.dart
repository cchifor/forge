import 'dart:math';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../chat_constants.dart';
import '../data/ag_ui_client.dart';
import '../data/agent_state_reducer.dart';
import '../domain/chat_message.dart';
import '../domain/user_prompt_payload.dart';
import '../domain/workspace_activity.dart';

const _modelKey = 'chat:model';
const _approvalKey = 'chat:approval';

/// Single Dio instance for AG-UI traffic. Kept separate from the app's main
/// `dioProvider` so chat timeouts and stream handling don't bleed into CRUD.
final agUiDioProvider = Provider<Dio>((ref) {
  return Dio(
    BaseOptions(
      receiveTimeout: const Duration(minutes: 10),
    ),
  );
});

final agUiClientProvider = Provider<AgUiClient>((ref) {
  return AgUiClient(dio: ref.watch(agUiDioProvider));
});

/// Selected LLM model (persisted to SharedPreferences).
class ChatModelNotifier extends Notifier<String> {
  @override
  String build() {
    _hydrate();
    return defaultModelId;
  }

  Future<void> _hydrate() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_modelKey);
    if (stored != null && availableModels.any((m) => m.id == stored)) {
      state = stored;
    }
  }

  Future<void> set(String id) async {
    if (!availableModels.any((m) => m.id == id)) return;
    state = id;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_modelKey, id);
  }
}

final chatModelProvider =
    NotifierProvider<ChatModelNotifier, String>(ChatModelNotifier.new);

/// Approval mode (default = ask before tools, bypass = auto-approve).
class ChatApprovalNotifier extends Notifier<ApprovalMode> {
  @override
  ApprovalMode build() {
    _hydrate();
    return defaultApprovalMode;
  }

  Future<void> _hydrate() async {
    final prefs = await SharedPreferences.getInstance();
    state = ApprovalModeX.fromWire(prefs.getString(_approvalKey));
  }

  Future<void> set(ApprovalMode mode) async {
    state = mode;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_approvalKey, mode.wireValue);
  }
}

final chatApprovalProvider =
    NotifierProvider<ChatApprovalNotifier, ApprovalMode>(ChatApprovalNotifier.new);

/// Optional auth-token getter — chat works in no-auth projects too.
final chatAuthTokenProvider = FutureProvider<String?>((ref) async {
  // Auth feature isn't always present (include_auth=false). Resolve dynamically
  // to avoid a hard import; widgets pass the token explicitly to the notifier.
  return null;
});

/// Holder for the chat thread. Owns messages, agent state, tool calls, and
/// orchestrates the AG-UI client. Single instance per app session.
class ChatNotifier extends Notifier<ChatStateSnapshot> {
  late String _threadId;

  @override
  ChatStateSnapshot build() {
    _threadId = _newId();
    return ChatStateSnapshot.empty;
  }

  String _newId() => '${DateTime.now().millisecondsSinceEpoch}-${Random().nextInt(1 << 32)}';

  /// Send a user message and stream the agent's response.
  Future<void> sendMessage(String content, {String? bearerToken}) async {
    final trimmed = content.trim();
    if (trimmed.isEmpty || state.isRunning) return;

    final userMsg = ChatMessage(
      id: _newId(),
      role: ChatRole.user,
      content: trimmed,
    );
    state = state.copyWith(
      messages: [...state.messages, userMsg],
      clearError: true,
    );
    await _runAgent(bearerToken: bearerToken);
  }

  /// Respond to a HITL prompt — sends an answer and resumes the run.
  Future<void> respondToPrompt(String answer, {String? bearerToken}) async {
    final prompt = state.pendingPrompt;
    if (prompt == null) return;
    final userMsg = ChatMessage(
      id: _newId(),
      role: ChatRole.user,
      content: answer,
    );
    state = state.copyWith(
      messages: [...state.messages, userMsg],
      clearPendingPrompt: true,
    );
    await _runAgent(
      bearerToken: bearerToken,
      forwardedProps: {
        'hitl_response': {'tool_call_id': prompt.toolCallId, 'answer': answer},
      },
    );
  }

  /// Reset the thread (new ID, empty state).
  void resetThread() {
    _threadId = _newId();
    state = ChatStateSnapshot.empty;
  }

  void clearCanvas() {
    state = state.copyWith(clearCanvas: true);
  }

  void clearWorkspaceActivity() {
    state = state.copyWith(clearWorkspace: true);
  }

  /// Manually open a workspace activity on the canvas (action callbacks).
  void setCanvasActivity(WorkspaceActivity activity) {
    state = state.copyWith(canvasActivity: activity);
  }

  Future<void> _runAgent({
    String? bearerToken,
    Map<String, dynamic> forwardedProps = const {},
  }) async {
    final client = ref.read(agUiClientProvider);
    final model = ref.read(chatModelProvider);
    final approval = ref.read(chatApprovalProvider);

    final wireMessages = state.messages.map((m) => m.toJson()).toList();
    final mergedProps = {
      'model': model,
      'approval': approval.wireValue,
      ...forwardedProps,
    };

    state = state.copyWith(isRunning: true, clearError: true);

    try {
      final stream = client.runAgent(
        threadId: _threadId,
        runId: _newId(),
        messages: wireMessages,
        state: state.rawAgentMap,
        forwardedProps: mergedProps,
        bearerToken: bearerToken,
      );
      await for (final event in stream) {
        state = reduce(state, event);
      }
    } catch (e) {
      state = state.copyWith(isRunning: false, error: e.toString());
    } finally {
      if (state.isRunning) {
        state = state.copyWith(isRunning: false);
      }
    }
  }
}

final chatProvider =
    NotifierProvider<ChatNotifier, ChatStateSnapshot>(ChatNotifier.new);

/// Convenience selectors so widgets only rebuild on the slice they care about.
final chatMessagesProvider = Provider<List<ChatMessage>>(
  (ref) => ref.watch(chatProvider.select((s) => s.messages)),
);

final chatIsRunningProvider = Provider<bool>(
  (ref) => ref.watch(chatProvider.select((s) => s.isRunning)),
);

final chatErrorProvider = Provider<String?>(
  (ref) => ref.watch(chatProvider.select((s) => s.error)),
);

final chatPendingPromptProvider = Provider<UserPromptPayload?>(
  (ref) => ref.watch(chatProvider.select((s) => s.pendingPrompt)),
);

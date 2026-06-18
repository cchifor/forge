import 'dart:math';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:forge_canvas/forge_canvas.dart' as fc;
import 'package:shared_preferences/shared_preferences.dart';

import '../chat_constants.dart';
import '../data/ag_ui_event.dart';
import '../data/agent_state_reducer.dart';
import '../domain/chat_message.dart';
import '../domain/user_prompt_payload.dart';
import '../domain/workspace_activity.dart';
{%- if include_auth %}
import '../../auth/data/auth_repository.dart';
{%- endif %}

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

final agUiClientProvider = Provider<fc.AgUiClient<AgUiEvent>>((ref) {
  return fc.AgUiClient<AgUiEvent>(
    dio: ref.watch(agUiDioProvider),
    parser: AgUiEvent.parse,
    onParseError: (payload) =>
        UnknownEvent(type: '__parse_error__', raw: {'data': payload}),
  );
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
{%- if include_auth %}
  // Auth is enabled: surface the current access token so native (mobile /
  // desktop) chat sends `Authorization: Bearer <token>` to the agent. On web,
  // Gatekeeper HttpOnly cookies carry auth, so accessToken is null there and
  // the bearer is simply omitted.
  return ref.read(authRepositoryProvider).accessToken;
{%- else %}
  // No auth feature in this project (include_auth=false) — nothing to send;
  // widgets pass any token explicitly to the notifier.
  return null;
{%- endif %}
});

/// Holder for the chat thread. Owns messages, agent state, tool calls, and
/// orchestrates the AG-UI client. Single instance per app session.
class ChatNotifier extends Notifier<ChatStateSnapshot> {
  late String _threadId;

  // Snapshot of the last `_runAgent` payload — retained so the
  // RUN_ERROR banner's "Retry" button can re-issue the same request
  // (same thread + same forwarded props) without forcing the user
  // to retype. `_hasRun` tracks whether any run has happened, since
  // an empty forwardedProps map is a valid payload.
  String? _lastBearerToken;
  Map<String, dynamic> _lastForwardedProps = const {};
  bool _hasRun = false;
  // Stale-run guard (mirrors Vue/Svelte). Each run captures the current
  // generation; resetThread bumps it so a still-arriving stream from a
  // superseded run can't repopulate the cleared state (ghost messages) or
  // flip isRunning after the user moved on. (audit #7)
  int _runGeneration = 0;

  @override
  ChatStateSnapshot build() {
    _threadId = _newId();
    return ChatStateSnapshot.empty;
  }

  String _newId() => '${DateTime.now().millisecondsSinceEpoch}-${Random().nextInt(1 << 32)}';

  /// Send a user message and stream the agent's response.
  ///
  /// [attachmentIds] are IDs returned by `POST /api/v1/chat-files` for
  /// this turn — surfaced to the agent as `attachment_ids` in
  /// `forwardedProps` (snake_case for the Python backend). Empty by
  /// default. Allows attachment-only sends (empty text but non-empty
  /// `attachmentIds`); rejects truly empty sends.
  Future<void> sendMessage(
    String content, {
    String? bearerToken,
    List<String> attachmentIds = const [],
  }) async {
    final trimmed = content.trim();
    if ((trimmed.isEmpty && attachmentIds.isEmpty) || state.isRunning) return;

    final userMsg = ChatMessage(
      id: _newId(),
      role: ChatRole.user,
      content: trimmed,
    );
    state = state.copyWith(
      messages: [...state.messages, userMsg],
      clearError: true,
    );
    await _runAgent(
      bearerToken: bearerToken,
      forwardedProps: attachmentIds.isNotEmpty
          ? {'attachment_ids': attachmentIds}
          : const {},
    );
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
    // Supersede any in-flight run so its late events can't repopulate the
    // freshly-cleared thread. (audit #7)
    _runGeneration += 1;
    state = ChatStateSnapshot.empty;
    _lastBearerToken = null;
    _lastForwardedProps = const {};
    _hasRun = false;
  }

  /// Re-issue the last `_runAgent` call after a RUN_ERROR. Reuses
  /// the same `_threadId` (conversation context is preserved) and
  /// replays the original forwarded props (model + approval +
  /// attachments). No-op before any run has happened.
  Future<void> retryLastRun() async {
    if (!_hasRun || state.isRunning) return;
    await _runAgent(
      bearerToken: _lastBearerToken,
      forwardedProps: _lastForwardedProps,
    );
  }

  /// Regenerate from `messageId` — truncates messages from that id
  /// onward (drops the message + everything after) and re-runs the
  /// agent on the SAME `_threadId` so conversational context is
  /// preserved. Distinct from a thread reset.
  ///
  /// Re-uses the last forwarded props (model + approval + attachments)
  /// so a regenerate following attachments doesn't lose them. No-op
  /// if the id isn't found OR a run is in flight (double clicks must
  /// not queue two runs).
  Future<void> regenerate(String messageId) async {
    // Codex Phase B round 1 follow-up: gate on `_hasRun` so a call
    // after resetThread() (or before any runAgent fired) doesn't fall
    // through to _runAgent with default empty _lastForwardedProps —
    // which would silently drop the model / approval / attachment_ids
    // the user expected to carry over. Same pattern as retryLastRun.
    if (!_hasRun || state.isRunning) return;
    final idx = state.messages.indexWhere((m) => m.id == messageId);
    if (idx == -1) return;
    state = state.copyWith(
      messages: state.messages.sublist(0, idx),
      clearError: true,
    );
    await _runAgent(
      bearerToken: _lastBearerToken,
      forwardedProps: _lastForwardedProps,
    );
  }

  /// Clear the RUN_ERROR banner without retrying.
  void dismissError() {
    if (state.error == null) return;
    state = state.copyWith(clearError: true);
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

    // Remember the exact payload so `retryLastRun` can re-issue it
    // verbatim. Capture BEFORE the request so a thrown error still
    // leaves retry armed.
    //
    // Codex Phase B round 1 follow-up: capture the FULLY-MERGED props
    // (including model + approval at this moment), not just the raw
    // forwardedProps. Otherwise a user who changes model/approval
    // between failure and retry sees a different request shape on
    // retry — that violates the "retry replays the failed request
    // verbatim" contract and diverges from Vue/Svelte semantics.
    _lastBearerToken = bearerToken;
    _lastForwardedProps = Map<String, dynamic>.from(mergedProps);
    _hasRun = true;
    final myGeneration = ++_runGeneration;

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
        // Drop events from a run the user superseded (reset) — they would
        // otherwise re-add ghost messages into the cleared state. Returning
        // from the await-for also cancels the stream subscription. (audit #7)
        if (myGeneration != _runGeneration) return;
        state = reduce(state, event);
      }
    } catch (e) {
      if (myGeneration != _runGeneration) return;
      state = state.copyWith(isRunning: false, error: e.toString());
    } finally {
      if (myGeneration == _runGeneration && state.isRunning) {
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

/// Mirrors the Vue/Svelte `AgentState` shape produced by the deepagent backend.
///
/// Plain Dart (no freezed) so the chat module doesn't pull in build_runner just
/// for protocol types. The reducer applies JSON Patch RFC 6902 deltas to a
/// `Map<String, dynamic>`, then re-derives this view object on the way out.
class AgentTodo {
  const AgentTodo({required this.content, required this.status});

  factory AgentTodo.fromJson(Map<String, dynamic> json) => AgentTodo(
        content: json['content']?.toString() ?? '',
        status: json['status']?.toString() ?? 'pending',
      );

  final String content;
  final String status;
}

class AgentUpload {
  const AgentUpload({required this.name, required this.path, required this.size});

  factory AgentUpload.fromJson(Map<String, dynamic> json) => AgentUpload(
        name: json['name']?.toString() ?? '',
        path: json['path']?.toString() ?? '',
        size: (json['size'] as num?)?.toInt() ?? 0,
      );

  final String name;
  final String path;
  final int size;
}

class AgentCost {
  const AgentCost({
    this.totalUsd = 0,
    this.totalTokens = 0,
    this.runUsd = 0,
    this.runTokens = 0,
  });

  factory AgentCost.fromJson(Map<String, dynamic> json) => AgentCost(
        totalUsd: (json['total_usd'] as num?)?.toDouble() ?? 0,
        totalTokens: (json['total_tokens'] as num?)?.toInt() ?? 0,
        runUsd: (json['run_usd'] as num?)?.toDouble() ?? 0,
        runTokens: (json['run_tokens'] as num?)?.toInt() ?? 0,
      );

  final double totalUsd;
  final int totalTokens;
  final double runUsd;
  final int runTokens;
}

class AgentContext {
  const AgentContext({
    this.usagePct = 0,
    this.currentTokens = 0,
    this.maxTokens = 0,
  });

  factory AgentContext.fromJson(Map<String, dynamic> json) => AgentContext(
        usagePct: (json['usage_pct'] as num?)?.toDouble() ?? 0,
        currentTokens: (json['current_tokens'] as num?)?.toInt() ?? 0,
        maxTokens: (json['max_tokens'] as num?)?.toInt() ?? 0,
      );

  final double usagePct;
  final int currentTokens;
  final int maxTokens;
}

class AgentState {
  const AgentState({
    this.todos = const [],
    this.files = const [],
    this.uploads = const [],
    this.cost,
    this.context,
    this.model,
    this.raw = const {},
  });

  factory AgentState.fromMap(Map<String, dynamic> map) => AgentState(
        todos: (map['todos'] as List?)
                ?.whereType<Map>()
                .map((e) => AgentTodo.fromJson(Map<String, dynamic>.from(e)))
                .toList() ??
            const [],
        files:
            (map['files'] as List?)?.whereType<String>().toList() ?? const [],
        uploads: (map['uploads'] as List?)
                ?.whereType<Map>()
                .map((e) => AgentUpload.fromJson(Map<String, dynamic>.from(e)))
                .toList() ??
            const [],
        cost: map['cost'] is Map
            ? AgentCost.fromJson(Map<String, dynamic>.from(map['cost'] as Map))
            : null,
        context: map['context'] is Map
            ? AgentContext.fromJson(
                Map<String, dynamic>.from(map['context'] as Map),
              )
            : null,
        model: map['model']?.toString(),
        raw: map,
      );

  final List<AgentTodo> todos;
  final List<String> files;
  final List<AgentUpload> uploads;
  final AgentCost? cost;
  final AgentContext? context;
  final String? model;
  // Untouched payload — workspace/canvas activities and bespoke deepagent fields
  // surface here so the UI can render unknown keys without a migration.
  final Map<String, dynamic> raw;

  static const empty = AgentState();
}

enum AgentEngine { agUi, mcpExt }

class WorkspaceActivity {
  const WorkspaceActivity({
    required this.engine,
    required this.activityType,
    required this.messageId,
    required this.content,
  });

  final AgentEngine engine;
  final String activityType;
  final String messageId;
  final Map<String, dynamic> content;
}

class WorkspaceAction {
  const WorkspaceAction({required this.type, required this.data});

  Map<String, dynamic> toJson() => {'type': type, 'data': data};

  final String type;
  final Map<String, dynamic> data;
}

class ChatModel {
  const ChatModel({required this.id, required this.label});
  final String id;
  final String label;
}

const availableModels = <ChatModel>[
  ChatModel(id: 'gpt-4.1', label: 'GPT-4.1'),
  ChatModel(id: 'gpt-4.1-mini', label: 'GPT-4.1 Mini'),
  ChatModel(id: 'claude-sonnet-4', label: 'Claude Sonnet 4'),
];

enum ApprovalMode { defaultMode, bypass }

extension ApprovalModeX on ApprovalMode {
  String get label =>
      this == ApprovalMode.bypass ? 'Bypass' : 'Default';

  String get wireValue =>
      this == ApprovalMode.bypass ? 'bypass' : 'default';

  static ApprovalMode fromWire(String? value) =>
      value == 'bypass' ? ApprovalMode.bypass : ApprovalMode.defaultMode;
}

const defaultModelId = 'claude-sonnet-4';
const defaultApprovalMode = ApprovalMode.defaultMode;

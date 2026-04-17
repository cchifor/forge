class UserPromptOption {
  const UserPromptOption({
    required this.label,
    this.description,
    this.recommended,
  });

  factory UserPromptOption.fromJson(Map<String, dynamic> json) =>
      UserPromptOption(
        label: json['label']?.toString() ?? '',
        description: json['description']?.toString(),
        recommended: json['recommended']?.toString(),
      );

  final String label;
  final String? description;
  final String? recommended;
}

class UserPromptPayload {
  const UserPromptPayload({
    required this.toolCallId,
    required this.question,
    required this.options,
  });

  factory UserPromptPayload.fromJson(Map<String, dynamic> json) =>
      UserPromptPayload(
        toolCallId: json['tool_call_id']?.toString() ?? '',
        question: json['question']?.toString() ?? '',
        options: (json['options'] as List?)
                ?.whereType<Map>()
                .map((e) =>
                    UserPromptOption.fromJson(Map<String, dynamic>.from(e)))
                .toList() ??
            const [],
      );

  final String toolCallId;
  final String question;
  final List<UserPromptOption> options;
}

class HitlResponse {
  const HitlResponse({required this.toolCallId, required this.answer});

  Map<String, dynamic> toJson() => {
        'tool_call_id': toolCallId,
        'answer': answer,
      };

  final String toolCallId;
  final String answer;
}

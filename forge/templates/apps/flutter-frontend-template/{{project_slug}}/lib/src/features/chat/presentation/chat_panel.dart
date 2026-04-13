import 'package:flutter/material.dart';

import 'chat_context_toggle.dart';
import 'chat_input_bar.dart';
import 'chat_message_list.dart';

class ChatPanel extends StatelessWidget {
  const ChatPanel({this.isFullScreen = false, super.key});

  final bool isFullScreen;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return ColoredBox(
      color: theme.colorScheme.surface,
      child: const Column(
        children: [
          ChatContextToggle(),
          Expanded(child: ChatMessageList()),
          ChatInputBar(),
        ],
      ),
    );
  }
}

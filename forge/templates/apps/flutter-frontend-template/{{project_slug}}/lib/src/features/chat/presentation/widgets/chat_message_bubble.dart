import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../../domain/chat_message.dart';
import '../../domain/tool_call_info.dart';
import 'tool_call_status.dart';

/// Token-streaming markdown debounce.
///
/// Why: each TEXT_MESSAGE_CONTENT delta would otherwise re-parse the entire
/// assistant message through `flutter_markdown` and rebuild the rich-text
/// tree. Typing-rate tokens (~5-20/sec from typical models) thrash layout.
/// We collapse bursts into a single render every ~50ms and always flush on
/// stream end so the final tokens land within one frame.
const Duration kMarkdownDebounceDuration = Duration(milliseconds: 50);

class ChatMessageBubble extends StatefulWidget {
  const ChatMessageBubble({
    super.key,
    required this.message,
    this.toolCalls = const [],
  });

  final ChatMessage message;
  final List<ToolCallInfo> toolCalls;

  @override
  State<ChatMessageBubble> createState() => _ChatMessageBubbleState();
}

class _ChatMessageBubbleState extends State<ChatMessageBubble> {
  /// The markdown source actually rendered into the widget tree. Lags
  /// behind `widget.message.content` by up to `kMarkdownDebounceDuration`
  /// during streaming; converges synchronously on stream end.
  late String _renderedContent;
  Timer? _debounceTimer;

  @override
  void initState() {
    super.initState();
    _renderedContent = widget.message.content;
  }

  @override
  void didUpdateWidget(covariant ChatMessageBubble oldWidget) {
    super.didUpdateWidget(oldWidget);
    final contentChanged = oldWidget.message.content != widget.message.content;
    final streamingEnded =
        oldWidget.message.isStreaming && !widget.message.isStreaming;

    if (!contentChanged && !streamingEnded) return;

    if (!widget.message.isStreaming) {
      // Non-streaming update (initial render, edit replay, or stream end):
      // flush synchronously so the final tokens appear within one frame.
      // No setState needed — `didUpdateWidget` is followed by `build()` in
      // the same frame, so writing to the State field is sufficient.
      _debounceTimer?.cancel();
      _debounceTimer = null;
      _renderedContent = widget.message.content;
      return;
    }

    // Streaming: collapse rapid deltas into one render per debounce window.
    // The raw `widget.message.content` remains the source of truth — we only
    // debounce the parse step. The Timer callback fires outside the build
    // pipeline so it must use `setState` to schedule a fresh rebuild.
    _debounceTimer?.cancel();
    _debounceTimer = Timer(kMarkdownDebounceDuration, () {
      if (!mounted) return;
      setState(() => _renderedContent = widget.message.content);
    });
  }

  @override
  void dispose() {
    _debounceTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isUser = widget.message.role == ChatRole.user;
    final bg = isUser ? scheme.primary : scheme.surfaceContainerHigh;
    final fg = isUser ? scheme.onPrimary : scheme.onSurface;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.sizeOf(context).width * 0.85,
        ),
        child: Container(
          key: ValueKey('chat-message-${widget.message.id}'),
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_renderedContent.isEmpty && widget.message.isStreaming)
                _BlinkCursor(color: fg)
              else
                MarkdownBody(
                  data: _renderedContent,
                  selectable: true,
                  styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
                    p: TextStyle(color: fg, height: 1.4),
                    code: TextStyle(
                      color: fg,
                      backgroundColor: bg.withValues(alpha: 0.1),
                      fontFamily: 'monospace',
                    ),
                  ),
                ),
              if (!isUser && widget.toolCalls.isNotEmpty) ...[
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: widget.toolCalls
                      .map((tc) => ToolCallStatusChip(toolCall: tc))
                      .toList(),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _BlinkCursor extends StatefulWidget {
  const _BlinkCursor({required this.color});
  final Color color;

  @override
  State<_BlinkCursor> createState() => _BlinkCursorState();
}

class _BlinkCursorState extends State<_BlinkCursor>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 700),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _controller,
      child: Container(
        width: 6,
        height: 14,
        color: widget.color,
      ),
    );
  }
}

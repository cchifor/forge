import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../theme/design_tokens.dart';
import '../../../theme/ai_theme_extension.dart';
import '../data/chat_attachments.dart';
import 'chat_providers.dart';

class ChatInputBar extends HookConsumerWidget {
  const ChatInputBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = useTextEditingController();
    final focusNode = useFocusNode();
    final theme = Theme.of(context);
    final aiColors = theme.extension<AiThemeColors>()!;
    final isGenerating = ref.watch(chatIsRunningProvider);
    final attachmentsState = ref.watch(chatAttachmentsProvider);
    final attachmentsCtrl = ref.read(chatAttachmentsProvider.notifier);
{%- if include_auth %}
    // Eagerly resolve the auth token so it's available synchronously at send
    // time (the provider wraps a sync accessToken getter). Null on web, where
    // Gatekeeper HttpOnly cookies carry auth instead of a bearer.
    ref.watch(chatAuthTokenProvider);
{%- endif %}

    Future<void> pickFiles() async {
      try {
        final files = await openFiles();
        if (files.isEmpty) return;
        // Read bytes for each picked file. `file_selector` returns
        // `XFile` which abstracts the platform-specific source (web
        // blob vs native path); `readAsBytes()` works uniformly.
        final payloads = <({String name, List<int> bytes, String? mimeType})>[];
        for (final f in files) {
          payloads.add((
            name: f.name,
            bytes: await f.readAsBytes(),
            mimeType: f.mimeType,
          ));
        }
        await attachmentsCtrl.addFiles(payloads);
      } catch (e) {
        if (!context.mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not pick file: $e')),
        );
      }
    }

    void send() {
      final text = controller.text.trim();
      final ids = attachmentsCtrl.ids;
      // ChatNotifier.sendMessage enforces the "text or attachments"
      // invariant; this short-circuit mirrors it locally so we don't
      // clear the input on a no-op.
      if ((text.isEmpty && ids.isEmpty) || isGenerating) return;
      ref.read(chatProvider.notifier).sendMessage(
            text,
{%- if include_auth %}
            bearerToken: ref.read(chatAuthTokenProvider).value,
{%- endif %}
            attachmentIds: ids,
          );
      controller.clear();
      attachmentsCtrl.clear();
    }

    String formatBytes(int? n) {
      if (n == null || n <= 0) return '';
      if (n < 1024) return '${n}B';
      if (n < 1024 * 1024) return '${(n / 1024).round()}KB';
      return '${(n / (1024 * 1024)).toStringAsFixed(1)}MB';
    }

    return Container(
      padding: const EdgeInsets.all(DesignTokens.p12),
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(
            color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
          ),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          // Attachment chips (Pillar G.1) — shown above the input row
          // when files are staged for the next send.
          if (attachmentsState.attachments.isNotEmpty ||
              attachmentsState.uploading ||
              attachmentsState.error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: DesignTokens.p8),
              child: Wrap(
                spacing: DesignTokens.p8,
                runSpacing: DesignTokens.p4,
                children: [
                  for (final att in attachmentsState.attachments)
                    Chip(
                      key: ValueKey('chat-attachment-${att.id}'),
                      label: Text(
                        att.sizeBytes != null
                            ? '${att.filename} · ${formatBytes(att.sizeBytes)}'
                            : att.filename,
                        style: theme.textTheme.bodySmall,
                      ),
                      deleteIcon: const Icon(Icons.close, size: 16),
                      onDeleted: () => attachmentsCtrl.removeAttachment(att.id),
                      visualDensity: VisualDensity.compact,
                    ),
                  if (attachmentsState.uploading)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p8),
                      child: Text(
                        'Uploading…',
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                  if (attachmentsState.error != null)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p8),
                      child: Text(
                        attachmentsState.error!,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.error,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          Container(
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(DesignTokens.radiusLarge),
              border: Border.all(
                color: isGenerating
                    ? aiColors.gradientStart.withValues(alpha: 0.5)
                    : theme.colorScheme.outlineVariant,
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Padding(
                  padding: const EdgeInsets.only(
                    left: DesignTokens.p4,
                    bottom: DesignTokens.p4,
                  ),
                  child: IconButton(
                    key: const ValueKey('chat-attach-button'),
                    onPressed: (attachmentsState.uploading || isGenerating)
                        ? null
                        : pickFiles,
                    icon: const Icon(Icons.attach_file_rounded),
                    tooltip: 'Attach file',
                    visualDensity: VisualDensity.compact,
                  ),
                ),
                Expanded(
                  child: TextField(
                    controller: controller,
                    focusNode: focusNode,
                    maxLines: 4,
                    minLines: 1,
                    enabled: !isGenerating,
                    onSubmitted: (_) => send(),
                    decoration: const InputDecoration(
                      hintText: 'Ask anything...',
                      border: InputBorder.none,
                      contentPadding: EdgeInsets.symmetric(
                        horizontal: DesignTokens.p8,
                        vertical: DesignTokens.p12,
                      ),
                    ),
                    textInputAction: TextInputAction.send,
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.only(
                    right: DesignTokens.p4,
                    bottom: DesignTokens.p4,
                  ),
                  child: IconButton(
                    key: const ValueKey('chat-send-button'),
                    onPressed: isGenerating ? null : send,
                    icon: ShaderMask(
                      shaderCallback: (bounds) => aiColors.gradient.createShader(bounds),
                      child: const Icon(Icons.send_rounded, color: Colors.white),
                    ),
                    tooltip: 'Send',
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

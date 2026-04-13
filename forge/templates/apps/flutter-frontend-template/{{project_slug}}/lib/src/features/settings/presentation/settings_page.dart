import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../theme/design_tokens.dart';
import '../../../theme/theme_provider.dart';
import 'widgets/color_scheme_picker.dart';
import 'widgets/theme_mode_selector.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final darkVariant = ref.watch(darkModeVariantProvider);

    return Scaffold(
      body: ListView(
        padding: const EdgeInsets.all(DesignTokens.p16),
        children: [
          Text('Appearance', style: theme.textTheme.titleMedium),
          const SizedBox(height: DesignTokens.p16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(DesignTokens.p16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Theme Mode', style: theme.textTheme.titleSmall),
                  const SizedBox(height: DesignTokens.p12),
                  const Center(child: ThemeModeSelector()),
                ],
              ),
            ),
          ),
          const SizedBox(height: DesignTokens.p16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(DesignTokens.p16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Dark Mode Variant', style: theme.textTheme.titleSmall),
                  const SizedBox(height: DesignTokens.p4),
                  Text(
                    'OLED uses pure black backgrounds for maximum contrast',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: DesignTokens.p12),
                  Center(
                    child: SegmentedButton<DarkModeVariant>(
                      segments: const [
                        ButtonSegment(
                          value: DarkModeVariant.standard,
                          icon: Icon(Icons.dark_mode),
                          label: Text('Standard'),
                        ),
                        ButtonSegment(
                          value: DarkModeVariant.oled,
                          icon: Icon(Icons.brightness_1),
                          label: Text('OLED'),
                        ),
                      ],
                      selected: {darkVariant},
                      onSelectionChanged: (selected) {
                        ref
                            .read(darkModeVariantProvider.notifier)
                            .setVariant(selected.first);
                      },
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: DesignTokens.p16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(DesignTokens.p16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Color Scheme', style: theme.textTheme.titleSmall),
                  const SizedBox(height: DesignTokens.p12),
                  const ColorSchemePicker(),
                ],
              ),
            ),
          ),
          const SizedBox(height: DesignTokens.p24),
          Text('About', style: theme.textTheme.titleMedium),
          const SizedBox(height: DesignTokens.p16),
          const Card(
            child: Column(
              children: [
                ListTile(
                  leading: Icon(Icons.info_outline),
                  title: Text('Version'),
                  subtitle: Text('0.1.0'),
                ),
                ListTile(
                  leading: Icon(Icons.code),
                  title: Text('Built with'),
                  subtitle: Text('Flutter + Riverpod'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

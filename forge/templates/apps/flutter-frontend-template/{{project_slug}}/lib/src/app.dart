import 'package:flutter/material.dart';
{%- if include_chat %}
import 'package:flutter/services.dart';
{%- endif %}
import 'package:hooks_riverpod/hooks_riverpod.dart';

import 'routing/app_router.dart';
import 'shared/feedback/feedback_service.dart';
{%- if include_chat %}
import 'shared/layout/layout_state.dart';
{%- endif %}
import 'theme/app_theme.dart';
import 'theme/theme_provider.dart';

class App extends HookConsumerWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeMode = ref.watch(themeModeProvider);
    final flexScheme = ref.watch(flexSchemeProvider);
    final darkVariant = ref.watch(darkModeVariantProvider);
    final textSize = ref.watch(textSizeProvider);
    final router = ref.watch(goRouterProvider);
    final messengerKey = ref.watch(scaffoldMessengerKeyProvider);

    // Apply the in-app text-size axis as the authoritative text scale (mirrors
    // the web build's `--font-size`). Overrides the OS scale by design — the
    // Settings control IS the user's text-size knob for this app.
    Widget applyTextScale(BuildContext context, Widget? child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textSize.scale)),
          child: child!,
        );

{%- if include_chat %}
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.keyJ, control: true):
            () => ref
                .read(layoutStateProvider.notifier)
                .toggleChatPanel(),
      },
      child: MaterialApp.router(
        title: '{{project_name}}',
        debugShowCheckedModeBanner: false,
        scaffoldMessengerKey: messengerKey,
        theme: lightTheme(flexScheme),
        darkTheme: darkVariant == DarkModeVariant.oled
            ? oledDarkTheme(flexScheme)
            : darkTheme(flexScheme),
        themeMode: themeMode,
        builder: applyTextScale,
        routerConfig: router,
      ),
    );
{%- else %}
    return MaterialApp.router(
      title: '{{project_name}}',
      debugShowCheckedModeBanner: false,
      scaffoldMessengerKey: messengerKey,
      theme: lightTheme(flexScheme),
      darkTheme: darkVariant == DarkModeVariant.oled
          ? oledDarkTheme(flexScheme)
          : darkTheme(flexScheme),
      themeMode: themeMode,
      builder: applyTextScale,
      routerConfig: router,
    );
{%- endif %}
  }
}

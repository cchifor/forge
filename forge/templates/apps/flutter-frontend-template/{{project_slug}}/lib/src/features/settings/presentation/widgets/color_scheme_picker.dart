import 'package:flex_color_scheme/flex_color_scheme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../theme/design_tokens.dart';
import '../../../../theme/theme_provider.dart';

class ColorSchemePicker extends ConsumerWidget {
  const ColorSchemePicker({super.key});

  static const _schemes = [
    FlexScheme.blue,
    FlexScheme.indigo,
    FlexScheme.hippieBlue,
    FlexScheme.aquaBlue,
    FlexScheme.tealM3,
    FlexScheme.verdunHemlock,
    FlexScheme.greenM3,
    FlexScheme.money,
    FlexScheme.gold,
    FlexScheme.mango,
    FlexScheme.amber,
    FlexScheme.vesuviusBurn,
    FlexScheme.deepPurple,
    FlexScheme.sakura,
    FlexScheme.redM3,
    FlexScheme.redWine,
    FlexScheme.rosewood,
    FlexScheme.blumineBlue,
    FlexScheme.cyanM3,
    FlexScheme.bahamaBlue,
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final currentScheme = ref.watch(flexSchemeProvider);

    return Wrap(
      spacing: DesignTokens.p8,
      runSpacing: DesignTokens.p8,
      children: _schemes.map((scheme) {
        final schemeDef = FlexColor.schemes[scheme];
        final primaryColor =
            schemeDef?.light.primary ?? Theme.of(context).colorScheme.primary;
        final isSelected = scheme == currentScheme;

        return _ColorSchemeChip(
          scheme: scheme,
          primaryColor: primaryColor,
          isSelected: isSelected,
          onTap: () {
            ref.read(flexSchemeProvider.notifier).setScheme(scheme);
          },
        );
      }).toList(),
    );
  }
}

class _ColorSchemeChip extends StatelessWidget {
  const _ColorSchemeChip({
    required this.scheme,
    required this.primaryColor,
    required this.isSelected,
    required this.onTap,
  });

  final FlexScheme scheme;
  final Color primaryColor;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: scheme.name,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(DesignTokens.radiusXLarge),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: DesignTokens.durationNormal),
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: primaryColor,
            shape: BoxShape.circle,
            border: isSelected
                ? Border.all(
                    color: Theme.of(context).colorScheme.outline,
                    width: 3,
                  )
                : null,
          ),
          child: isSelected
              ? Icon(
                  Icons.check,
                  color:
                      ThemeData.estimateBrightnessForColor(primaryColor) ==
                              Brightness.dark
                          ? Colors.white
                          : Colors.black,
                  size: DesignTokens.iconMD,
                )
              : null,
        ),
      ),
    );
  }
}

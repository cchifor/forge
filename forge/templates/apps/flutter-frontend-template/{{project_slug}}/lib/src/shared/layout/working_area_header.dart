import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';
import '../widgets/chat_button.dart';
import 'breadcrumb_bar.dart';

class WorkingAreaHeader extends StatelessWidget {
  const WorkingAreaHeader({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: DesignTokens.workingAreaHeaderHeight,
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p16),
      child: const Row(
        children: [
          BreadcrumbBar(),
          Spacer(),
          ChatButton(),
        ],
      ),
    );
  }
}

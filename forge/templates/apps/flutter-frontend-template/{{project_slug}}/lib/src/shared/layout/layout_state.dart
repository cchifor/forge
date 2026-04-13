import 'package:freezed_annotation/freezed_annotation.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../theme/design_tokens.dart';
import '../../core/storage/key_value_storage.dart';

part 'layout_state.freezed.dart';
part 'layout_state.g.dart';

enum LayoutBreakpoint { compact, medium, expanded }

@freezed
abstract class LayoutState with _$LayoutState {
  const factory LayoutState({
    @Default(true) bool sidebarExpanded,
    @Default(false) bool chatPanelOpen,
    @Default(840.0) double screenWidth,
    @Default(0.33) double chatWidthRatio,
  }) = _LayoutState;

  const LayoutState._();

  LayoutBreakpoint get breakpoint {
    if (screenWidth < DesignTokens.compactWidth) return LayoutBreakpoint.compact;
    if (screenWidth < DesignTokens.expandedWidth) return LayoutBreakpoint.medium;
    return LayoutBreakpoint.expanded;
  }

  bool get isMobile => breakpoint == LayoutBreakpoint.compact;
  bool get isMedium => breakpoint == LayoutBreakpoint.medium;

  double get effectiveSidebarWidth {
    if (isMobile) return 0;
    if (isMedium) return DesignTokens.sidebarCollapsedWidth;
    return sidebarExpanded
        ? DesignTokens.sidebarExpandedWidth
        : DesignTokens.sidebarCollapsedWidth;
  }

  bool get chatInline =>
      breakpoint == LayoutBreakpoint.expanded && chatPanelOpen;
}

const _sidebarExpandedKey = 'sidebar_expanded';
const _chatWidthRatioKey = 'chat_width_ratio';

@Riverpod(keepAlive: true)
class LayoutStateNotifier extends _$LayoutStateNotifier {
  SharedPreferences get _prefs => ref.read(keyValueStorageProvider);

  @override
  LayoutState build() {
    final sidebarPersisted = _prefs.getBool(_sidebarExpandedKey) ?? true;
    final ratioPersisted = _prefs.getDouble(_chatWidthRatioKey) ?? 0.33;
    return LayoutState(
      sidebarExpanded: sidebarPersisted,
      chatWidthRatio: ratioPersisted.clamp(0.05, 0.95),
    );
  }

  void setScreenWidth(double width) {
    if (state.screenWidth == width) return;
    var next = state.copyWith(screenWidth: width);

    if (next.breakpoint != LayoutBreakpoint.expanded && next.sidebarExpanded) {
      next = next.copyWith(sidebarExpanded: false);
    }
    state = next;
  }

  void toggleSidebar() {
    final expanded = !state.sidebarExpanded;
    state = state.copyWith(sidebarExpanded: expanded);
    _prefs.setBool(_sidebarExpandedKey, expanded);
  }

  void toggleChatPanel() {
    state = state.copyWith(chatPanelOpen: !state.chatPanelOpen);
  }

  void setChatPanelOpen(bool open) {
    if (state.chatPanelOpen == open) return;
    state = state.copyWith(chatPanelOpen: open);
  }

  /// Update ratio in memory only (no I/O). Call on every drag frame.
  /// Uses a generous clamp -- pixel-level enforcement happens in the layout.
  void setChatWidthRatio(double ratio) {
    state = state.copyWith(chatWidthRatio: ratio.clamp(0.05, 0.95));
  }

  /// Persist the current ratio to disk. Call once on drag end.
  void commitChatWidthRatio() {
    _prefs.setDouble(_chatWidthRatioKey, state.chatWidthRatio);
  }

  void resetChatWidthRatio() {
    state = state.copyWith(chatWidthRatio: 0.33);
    _prefs.setDouble(_chatWidthRatioKey, 0.33);
  }
}

abstract final class DesignTokens {
  // ── Responsive breakpoints ──
  static const double compactWidth = 600;
  static const double mediumWidth = 840;
  static const double expandedWidth = 840;

  // ── Spacing scale (8px base) ──
  static const double p4 = 4;
  static const double p8 = 8;
  static const double p12 = 12;
  static const double p16 = 16;
  static const double p20 = 20;
  static const double p24 = 24;
  static const double p32 = 32;
  static const double p48 = 48;
  static const double p64 = 64;

  // ── Border radius ──
  static const double radiusSmall = 8;
  static const double radiusMedium = 12;
  static const double radiusLarge = 16;
  static const double radiusXLarge = 20;

  // ── Icon sizes ──
  static const double iconXS = 14;
  static const double iconSM = 16;
  static const double iconMD = 20;
  static const double iconLG = 24;
  static const double iconXL = 48;
  static const double iconHero = 80;

  // ── Avatar radii ──
  static const double avatarSM = 14;
  static const double avatarMD = 16;
  static const double avatarLG = 48;

  // ── Animation durations (ms) ──
  static const int durationFast = 100;
  static const int durationNormal = 200;
  static const int durationSlow = 300;
  static const int durationDebounce = 400;

  // ── Working area header ──
  static const double workingAreaHeaderHeight = 56;

  // ── Sidebar (used by Riverpod notifier, no BuildContext) ──
  static const double sidebarCollapsedWidth = 72;
  static const double sidebarExpandedWidth = 240;
  /// Horizontal padding applied to sidebar body content (ListView + header/footer).
  static const double sidebarBodyPadding = 8;
  /// Width of the icon column inside the sidebar. All icons/avatars center
  /// within this column so they align vertically in both collapsed and expanded modes.
  /// Equals `sidebarCollapsedWidth - sidebarBodyPadding * 2`.
  static const double sidebarIconColumnWidth = sidebarCollapsedWidth - sidebarBodyPadding * 2; // 56

  // ── Legacy (kept for backward compatibility) ──
  static const double navRailWidth = 72;
  static const double navRailExtendedWidth = 256;
}

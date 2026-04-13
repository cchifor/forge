import 'dart:ui';

import 'package:flutter/material.dart';

class LayoutThemeExtension extends ThemeExtension<LayoutThemeExtension> {
  const LayoutThemeExtension({
    this.minMainAreaWidth = 300,
    this.minChatWidth = 280,
    this.defaultChatRatio = 0.33,
    this.chatDrawerWidth = 360,
    this.chatHeaderHeight = 48,
    this.splitterWidth = 8,
    this.headerHeight = 56,
    this.loginCardMaxWidth = 400,
    this.labelWidth = 100,
  });

  /// Minimum pixel width for the main working area (prevents squish).
  final double minMainAreaWidth;

  /// Minimum pixel width for the inline chat panel.
  final double minChatWidth;

  /// Default chat-to-available-width ratio when first opened.
  final double defaultChatRatio;

  /// Width of the chat drawer on medium screens.
  final double chatDrawerWidth;

  /// Height of the chat panel's context toggle header.
  final double chatHeaderHeight;

  /// Hit area width for the vertical splitter handle.
  final double splitterWidth;

  /// Height of the working area top header (breadcrumbs + AI button).
  final double headerHeight;

  /// Max width constraint for the login card.
  final double loginCardMaxWidth;

  /// Fixed width for label columns in detail views.
  final double labelWidth;

  static const standard = LayoutThemeExtension();

  @override
  LayoutThemeExtension copyWith({
    double? minMainAreaWidth,
    double? minChatWidth,
    double? defaultChatRatio,
    double? chatDrawerWidth,
    double? chatHeaderHeight,
    double? splitterWidth,
    double? headerHeight,
    double? loginCardMaxWidth,
    double? labelWidth,
  }) {
    return LayoutThemeExtension(
      minMainAreaWidth: minMainAreaWidth ?? this.minMainAreaWidth,
      minChatWidth: minChatWidth ?? this.minChatWidth,
      defaultChatRatio: defaultChatRatio ?? this.defaultChatRatio,
      chatDrawerWidth: chatDrawerWidth ?? this.chatDrawerWidth,
      chatHeaderHeight: chatHeaderHeight ?? this.chatHeaderHeight,
      splitterWidth: splitterWidth ?? this.splitterWidth,
      headerHeight: headerHeight ?? this.headerHeight,
      loginCardMaxWidth: loginCardMaxWidth ?? this.loginCardMaxWidth,
      labelWidth: labelWidth ?? this.labelWidth,
    );
  }

  @override
  LayoutThemeExtension lerp(covariant LayoutThemeExtension? other, double t) {
    if (other == null) return this;
    return LayoutThemeExtension(
      minMainAreaWidth:
          lerpDouble(minMainAreaWidth, other.minMainAreaWidth, t)!,
      minChatWidth: lerpDouble(minChatWidth, other.minChatWidth, t)!,
      defaultChatRatio:
          lerpDouble(defaultChatRatio, other.defaultChatRatio, t)!,
      chatDrawerWidth:
          lerpDouble(chatDrawerWidth, other.chatDrawerWidth, t)!,
      chatHeaderHeight:
          lerpDouble(chatHeaderHeight, other.chatHeaderHeight, t)!,
      splitterWidth: lerpDouble(splitterWidth, other.splitterWidth, t)!,
      headerHeight: lerpDouble(headerHeight, other.headerHeight, t)!,
      loginCardMaxWidth:
          lerpDouble(loginCardMaxWidth, other.loginCardMaxWidth, t)!,
      labelWidth: lerpDouble(labelWidth, other.labelWidth, t)!,
    );
  }
}

// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

part 'health_component.g.dart';

@JsonSerializable()
class HealthComponent {
  const HealthComponent({
    required this.status,
    this.latencyMs,
    this.details,
  });
  
  factory HealthComponent.fromJson(Map<String, Object?> json) => _$HealthComponentFromJson(json);
  
  final String status;
  @JsonKey(name: 'latency_ms')
  final double? latencyMs;
  final dynamic details;

  Map<String, Object?> toJson() => _$HealthComponentToJson(this);
}

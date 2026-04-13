// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

import 'health_component.dart';

part 'readiness_response.g.dart';

@JsonSerializable()
class ReadinessResponse {
  const ReadinessResponse({
    required this.status,
    this.components,
    this.systemInfo,
  });
  
  factory ReadinessResponse.fromJson(Map<String, Object?> json) => _$ReadinessResponseFromJson(json);
  
  final String status;
  final Map<String, HealthComponent>? components;
  @JsonKey(name: 'system_info')
  final Map<String, String>? systemInfo;

  Map<String, Object?> toJson() => _$ReadinessResponseToJson(this);
}

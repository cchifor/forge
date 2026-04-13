// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

part 'liveness_response.g.dart';

@JsonSerializable()
class LivenessResponse {
  const LivenessResponse({
    required this.status,
    this.details,
  });
  
  factory LivenessResponse.fromJson(Map<String, Object?> json) => _$LivenessResponseFromJson(json);
  
  final String status;
  final String? details;

  Map<String, Object?> toJson() => _$LivenessResponseToJson(this);
}

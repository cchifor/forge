// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

part 'status_response.g.dart';

@JsonSerializable()
class StatusResponse {
  const StatusResponse({
    required this.status,
  });
  
  factory StatusResponse.fromJson(Map<String, Object?> json) => _$StatusResponseFromJson(json);
  
  final String status;

  Map<String, Object?> toJson() => _$StatusResponseToJson(this);
}

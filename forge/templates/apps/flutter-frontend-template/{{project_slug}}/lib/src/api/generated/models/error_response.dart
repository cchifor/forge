// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

import 'error_detail.dart';

part 'error_response.g.dart';

@JsonSerializable()
class ErrorResponse {
  const ErrorResponse({
    required this.message,
    this.type,
    this.detail,
  });
  
  factory ErrorResponse.fromJson(Map<String, Object?> json) => _$ErrorResponseFromJson(json);
  
  final String message;
  final String? type;
  final ErrorDetail? detail;

  Map<String, Object?> toJson() => _$ErrorResponseToJson(this);
}

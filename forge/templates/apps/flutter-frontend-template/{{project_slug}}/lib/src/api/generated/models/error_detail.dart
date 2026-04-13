// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

part 'error_detail.g.dart';

@JsonSerializable()
class ErrorDetail {
  const ErrorDetail({
    this.code,
    this.errors,
  });
  
  factory ErrorDetail.fromJson(Map<String, Object?> json) => _$ErrorDetailFromJson(json);
  
  final int? code;
  final List<String>? errors;

  Map<String, Object?> toJson() => _$ErrorDetailToJson(this);
}

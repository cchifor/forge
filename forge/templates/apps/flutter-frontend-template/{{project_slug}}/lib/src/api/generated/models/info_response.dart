// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

part 'info_response.g.dart';

@JsonSerializable()
class InfoResponse {
  const InfoResponse({
    required this.title,
    required this.version,
    required this.description,
  });
  
  factory InfoResponse.fromJson(Map<String, Object?> json) => _$InfoResponseFromJson(json);
  
  final String title;
  final String version;
  final String description;

  Map<String, Object?> toJson() => _$InfoResponseToJson(this);
}

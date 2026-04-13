// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

import 'task_status.dart';

part 'task_status_response.g.dart';

@JsonSerializable()
class TaskStatusResponse {
  const TaskStatusResponse({
    required this.id,
    required this.taskType,
    required this.status,
    required this.attempts,
    required this.maxRetries,
    this.payload,
    this.result,
    this.error,
    this.createdAt,
    this.startedAt,
    this.completedAt,
  });
  
  factory TaskStatusResponse.fromJson(Map<String, Object?> json) => _$TaskStatusResponseFromJson(json);
  
  final String id;
  @JsonKey(name: 'task_type')
  final String taskType;
  final TaskStatus status;
  final dynamic payload;
  final dynamic result;
  final String? error;
  final int attempts;
  @JsonKey(name: 'max_retries')
  final int maxRetries;
  @JsonKey(name: 'created_at')
  final DateTime? createdAt;
  @JsonKey(name: 'started_at')
  final DateTime? startedAt;
  @JsonKey(name: 'completed_at')
  final DateTime? completedAt;

  Map<String, Object?> toJson() => _$TaskStatusResponseToJson(this);
}

// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

part 'task_enqueue_response.g.dart';

@JsonSerializable()
class TaskEnqueueResponse {
  const TaskEnqueueResponse({
    required this.id,
    required this.taskType,
    required this.status,
  });
  
  factory TaskEnqueueResponse.fromJson(Map<String, Object?> json) => _$TaskEnqueueResponseFromJson(json);
  
  final String id;
  @JsonKey(name: 'task_type')
  final String taskType;
  final String status;

  Map<String, Object?> toJson() => _$TaskEnqueueResponseToJson(this);
}

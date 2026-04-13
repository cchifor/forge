// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

part 'task_enqueue_request.g.dart';

@JsonSerializable()
class TaskEnqueueRequest {
  const TaskEnqueueRequest({
    required this.taskType,
    this.maxRetries = 3,
    this.payload,
  });
  
  factory TaskEnqueueRequest.fromJson(Map<String, Object?> json) => _$TaskEnqueueRequestFromJson(json);
  
  @JsonKey(name: 'task_type')
  final String taskType;
  final dynamic payload;
  @JsonKey(name: 'max_retries')
  final int maxRetries;

  Map<String, Object?> toJson() => _$TaskEnqueueRequestToJson(this);
}

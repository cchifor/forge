// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:dio/dio.dart';
import 'package:retrofit/retrofit.dart';

import '../models/task_enqueue_request.dart';
import '../models/task_enqueue_response.dart';
import '../models/task_status_response.dart';

part 'tasks_client.g.dart';

@RestApi()
abstract class TasksClient {
  factory TasksClient(Dio dio, {String? baseUrl}) = _TasksClient;

  /// Enqueue Task
  @POST('/api/v1/tasks')
  Future<TaskEnqueueResponse> enqueueTask({
    @Body() required TaskEnqueueRequest body,
  });

  /// Get Task Status
  @GET('/api/v1/tasks/{task_id}')
  Future<TaskStatusResponse> getTaskStatus({
    @Path('task_id') required String taskId,
  });

  /// Cancel Task
  @DELETE('/api/v1/tasks/{task_id}')
  Future<void> cancelTask({
    @Path('task_id') required String taskId,
  });
}

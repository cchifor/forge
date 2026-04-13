// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:dio/dio.dart';

import 'home/home_client.dart';
import 'health/health_client.dart';
import 'items/items_client.dart';
import 'tasks/tasks_client.dart';

/// My Service `v0.1.0`.
///
/// A Python microservice template.
class RestClient {
  RestClient(
    Dio dio, {
    String? baseUrl,
  })  : _dio = dio,
        _baseUrl = baseUrl;

  final Dio _dio;
  final String? _baseUrl;

  static String get version => '0.1.0';

  HomeClient? _home;
  HealthClient? _health;
  ItemsClient? _items;
  TasksClient? _tasks;

  HomeClient get home => _home ??= HomeClient(_dio, baseUrl: _baseUrl);

  HealthClient get health => _health ??= HealthClient(_dio, baseUrl: _baseUrl);

  ItemsClient get items => _items ??= ItemsClient(_dio, baseUrl: _baseUrl);

  TasksClient get tasks => _tasks ??= TasksClient(_dio, baseUrl: _baseUrl);
}

// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:dio/dio.dart';
import 'package:retrofit/retrofit.dart';

import '../models/info_response.dart';
import '../models/status_response.dart';

part 'home_client.g.dart';

@RestApi()
abstract class HomeClient {
  factory HomeClient(Dio dio, {String? baseUrl}) = _HomeClient;

  /// Get Status
  @GET('/')
  Future<StatusResponse> getStatus();

  /// Get Info
  @GET('/info')
  Future<InfoResponse> getInfo();
}

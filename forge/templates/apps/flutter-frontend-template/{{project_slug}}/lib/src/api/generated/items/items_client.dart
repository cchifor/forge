// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:dio/dio.dart';
import 'package:retrofit/retrofit.dart';

import '../models/item.dart';
import '../models/item_create.dart';
import '../models/item_status.dart';
import '../models/item_update.dart';
import '../models/paginated_items_result.dart';

part 'items_client.g.dart';

@RestApi()
abstract class ItemsClient {
  factory ItemsClient(Dio dio, {String? baseUrl}) = _ItemsClient;

  /// List Items
  @GET('/api/v1/items')
  Future<PaginatedItemsResult> listItems({
    @Query('status') ItemStatus? status,
    @Query('search') String? search,
    @Query('skip') int? skip = 0,
    @Query('limit') int? limit = 50,
  });

  /// Create Item
  @POST('/api/v1/items')
  Future<Item> createItem({
    @Body() required ItemCreate body,
  });

  /// Get Item
  @GET('/api/v1/items/{item_id}')
  Future<Item> getItem({
    @Path('item_id') required String itemId,
  });

  /// Update Item
  @PATCH('/api/v1/items/{item_id}')
  Future<Item> updateItem({
    @Path('item_id') required String itemId,
    @Body() required ItemUpdate body,
  });

  /// Delete Item
  @DELETE('/api/v1/items/{item_id}')
  Future<void> deleteItem({
    @Path('item_id') required String itemId,
  });
}

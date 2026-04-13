// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

import 'item.dart';

part 'paginated_items_result.g.dart';

@JsonSerializable()
class PaginatedItemsResult {
  const PaginatedItemsResult({
    required this.items,
    required this.total,
    required this.skip,
    required this.limit,
    required this.hasMore,
  });
  
  factory PaginatedItemsResult.fromJson(Map<String, Object?> json) => _$PaginatedItemsResultFromJson(json);
  
  final List<Item> items;
  final int total;
  final int skip;
  final int limit;
  @JsonKey(name: 'has_more')
  final bool hasMore;

  Map<String, Object?> toJson() => _$PaginatedItemsResultToJson(this);
}

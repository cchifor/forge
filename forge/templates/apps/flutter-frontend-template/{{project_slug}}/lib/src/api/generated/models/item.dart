// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

import 'item_status.dart';

part 'item.g.dart';

@JsonSerializable()
class Item {
  const Item({
    required this.id,
    required this.name,
    required this.status,
    required this.customerId,
    required this.userId,
    this.tags = const [],
    this.description,
    this.createdAt,
    this.updatedAt,
  });
  
  factory Item.fromJson(Map<String, Object?> json) => _$ItemFromJson(json);
  
  final String id;
  final String name;
  final String? description;
  final List<String> tags;
  final ItemStatus status;
  @JsonKey(name: 'customer_id')
  final String customerId;
  @JsonKey(name: 'user_id')
  final String userId;
  @JsonKey(name: 'created_at')
  final DateTime? createdAt;
  @JsonKey(name: 'updated_at')
  final DateTime? updatedAt;

  Map<String, Object?> toJson() => _$ItemToJson(this);
}

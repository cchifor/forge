// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

import 'item_status.dart';

part 'item_create.g.dart';

@JsonSerializable()
class ItemCreate {
  const ItemCreate({
    required this.name,
    this.tags = const [],
    this.status = ItemStatus.draft,
    this.description,
  });
  
  factory ItemCreate.fromJson(Map<String, Object?> json) => _$ItemCreateFromJson(json);
  
  final String name;
  final String? description;
  final List<String> tags;
  final ItemStatus status;

  Map<String, Object?> toJson() => _$ItemCreateToJson(this);
}

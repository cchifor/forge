// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, unused_import, invalid_annotation_target, unnecessary_import

import 'package:json_annotation/json_annotation.dart';

import 'item_status.dart';

part 'item_update.g.dart';

@JsonSerializable()
class ItemUpdate {
  const ItemUpdate({
    this.name,
    this.description,
    this.tags,
    this.status,
  });
  
  factory ItemUpdate.fromJson(Map<String, Object?> json) => _$ItemUpdateFromJson(json);
  
  final String? name;
  final String? description;
  final List<String>? tags;
  final ItemStatus? status;

  Map<String, Object?> toJson() => _$ItemUpdateToJson(this);
}

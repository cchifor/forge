// Chat attachment upload helper — wraps `POST /api/v1/chat-files`.
//
// The backend route accepts multipart `file` + optional `customer_id`,
// returns `{id, filename, mime_type, size_bytes, storage_path}`. We
// surface only the fields `ChatInputBar` renders as a chip.
//
// Pillar G.1 (Flutter half) of the architectural improvement plan.
// Mirror of the Svelte + Vue helpers; same wire contract, dio-based
// because dio is already in the template's dep tree (`pubspec.yaml`
// line 25) and the Riverpod-managed instance threads through the
// auth / error interceptors automatically.

import 'package:dio/dio.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../api/client/dio_client.dart';

/// Chip-ready metadata for a staged-but-not-yet-sent attachment.
class ChatAttachment {
  const ChatAttachment({
    required this.id,
    required this.filename,
    this.mimeType,
    this.sizeBytes,
  });

  final String id;
  final String filename;
  final String? mimeType;
  final int? sizeBytes;
}

/// Typed exception so callers can distinguish upload failures from
/// generic dio exceptions and surface a specific message in the UI.
class ChatAttachmentUploadException implements Exception {
  ChatAttachmentUploadException(this.message, {this.statusCode, this.detail});
  final String message;
  final int? statusCode;
  final String? detail;
  @override
  String toString() => message;
}

/// State held by [ChatAttachments] — staged chips + transient
/// uploading / error flags surfaced in the input bar.
class ChatAttachmentsState {
  const ChatAttachmentsState({
    this.attachments = const [],
    this.uploading = false,
    this.error,
  });

  final List<ChatAttachment> attachments;
  final bool uploading;
  final String? error;

  ChatAttachmentsState copyWith({
    List<ChatAttachment>? attachments,
    bool? uploading,
    Object? error = _sentinel,
  }) {
    return ChatAttachmentsState(
      attachments: attachments ?? this.attachments,
      uploading: uploading ?? this.uploading,
      error: identical(error, _sentinel) ? this.error : error as String?,
    );
  }

  static const _sentinel = Object();
}

/// Riverpod-managed notifier wrapping the upload helper. One instance
/// per chat thread; `ChatInputBar` watches `attachments` for chips +
/// calls `addFiles` from its paperclip handler.
class ChatAttachments extends Notifier<ChatAttachmentsState> {
  @override
  ChatAttachmentsState build() => const ChatAttachmentsState();

  Future<void> addFiles(List<({String name, List<int> bytes, String? mimeType})> files) async {
    if (files.isEmpty) return;
    state = state.copyWith(uploading: true, error: null);
    final dio = ref.read(dioProvider);
    try {
      // Sequential uploads — bounded backend pressure + clean per-file
      // error attribution. Most users attach 1-3 files per turn.
      var staged = [...state.attachments];
      for (final file in files) {
        final attachment = await _uploadOne(dio, file);
        staged = [...staged, attachment];
        state = state.copyWith(attachments: staged);
      }
    } on ChatAttachmentUploadException catch (e) {
      state = state.copyWith(uploading: false, error: e.message);
      return;
    } catch (e) {
      state = state.copyWith(uploading: false, error: 'Upload failed: $e');
      return;
    }
    state = state.copyWith(uploading: false);
  }

  void removeAttachment(String id) {
    state = state.copyWith(
      attachments: state.attachments.where((a) => a.id != id).toList(),
    );
  }

  void clear() {
    state = const ChatAttachmentsState();
  }

  List<String> get ids => state.attachments.map((a) => a.id).toList();
}

final chatAttachmentsProvider =
    NotifierProvider<ChatAttachments, ChatAttachmentsState>(ChatAttachments.new);

Future<ChatAttachment> _uploadOne(
  Dio dio,
  ({String name, List<int> bytes, String? mimeType}) file,
) async {
  final form = FormData.fromMap({
    'file': MultipartFile.fromBytes(
      file.bytes,
      filename: file.name,
      contentType: file.mimeType != null ? DioMediaType.parse(file.mimeType!) : null,
    ),
  });
  Response<Map<String, dynamic>> response;
  try {
    response = await dio.post<Map<String, dynamic>>(
      '/api/v1/chat-files',
      data: form,
      options: Options(contentType: 'multipart/form-data'),
    );
  } on DioException catch (e) {
    final status = e.response?.statusCode ?? 0;
    final detail = e.response?.data?.toString() ?? e.message ?? '<no body>';
    throw ChatAttachmentUploadException(
      'Chat file upload failed (status $status): $detail',
      statusCode: status,
      detail: detail,
    );
  }
  final payload = response.data;
  if (payload == null || payload['id'] is! String || (payload['id'] as String).isEmpty) {
    throw ChatAttachmentUploadException(
      'Chat file upload returned no id',
      statusCode: response.statusCode,
      detail: payload?.toString(),
    );
  }
  return ChatAttachment(
    id: payload['id'] as String,
    filename: (payload['filename'] as String?) ?? file.name,
    mimeType: payload['mime_type'] as String?,
    sizeBytes: (payload['size_bytes'] as int?) ?? file.bytes.length,
  );
}

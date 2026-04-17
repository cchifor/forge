import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

import 'ag_ui_event.dart';

/// Connects to an AG-UI agent endpoint over Server-Sent Events.
///
/// The deepagent backend exposes `POST /agent/run` which returns an
/// `text/event-stream` response. Each frame is `data: {json}\n\n`. We accumulate
/// bytes until a blank line, parse the JSON, dispatch through `AgUiEvent.parse`,
/// and emit on the returned Stream.
class AgUiClient {
  AgUiClient({Dio? dio, String? baseUrl})
      : _dio = dio ?? Dio(),
        _baseUrl = baseUrl ?? '/agent/';

  final Dio _dio;
  final String _baseUrl;

  /// Run an agent with the given thread state. Returns a one-shot stream that
  /// completes when the server closes the SSE connection or emits RUN_FINISHED.
  Stream<AgUiEvent> runAgent({
    required String threadId,
    required String runId,
    required List<Map<String, dynamic>> messages,
    Map<String, dynamic> state = const {},
    Map<String, dynamic> forwardedProps = const {},
    String? bearerToken,
  }) async* {
    final headers = <String, dynamic>{
      'Accept': 'text/event-stream',
      'Content-Type': 'application/json',
      if (bearerToken != null && bearerToken.isNotEmpty)
        'Authorization': 'Bearer $bearerToken',
    };

    final body = {
      'threadId': threadId,
      'runId': runId,
      'messages': messages,
      'state': state,
      'tools': const <Map<String, dynamic>>[],
      'context': const <Map<String, dynamic>>[],
      'forwardedProps': forwardedProps,
    };

    Response<ResponseBody>? response;
    try {
      response = await _dio.post<ResponseBody>(
        _baseUrl,
        data: jsonEncode(body),
        options: Options(
          headers: headers,
          responseType: ResponseType.stream,
          receiveTimeout: const Duration(minutes: 10),
        ),
      );
    } on DioException catch (e) {
      yield RunErrorEvent(
        message: 'Agent request failed: ${e.message ?? e.type.name}',
      );
      return;
    }

    final stream = response.data?.stream;
    if (stream == null) {
      yield const RunErrorEvent(message: 'Agent returned an empty stream.');
      return;
    }

    final buffer = StringBuffer();
    try {
      await for (final chunk in stream.cast<List<int>>().transform(utf8.decoder)) {
        buffer.write(chunk);
        // Process complete events (terminated by blank line per SSE spec).
        while (true) {
          final text = buffer.toString();
          final separator = text.indexOf('\n\n');
          if (separator == -1) break;
          final frame = text.substring(0, separator);
          buffer.clear();
          buffer.write(text.substring(separator + 2));
          final event = _parseFrame(frame);
          if (event != null) yield event;
        }
      }
    } catch (e) {
      yield RunErrorEvent(message: 'Stream error: $e');
    }
  }

  AgUiEvent? _parseFrame(String frame) {
    // SSE frame: one or more `field: value` lines. We only consume `data:`.
    final dataLines = <String>[];
    for (final line in const LineSplitter().convert(frame)) {
      if (line.startsWith('data:')) {
        dataLines.add(line.substring(5).trimLeft());
      } else if (line.startsWith(':') || line.isEmpty) {
        // Comment or keep-alive — skip.
      }
    }
    if (dataLines.isEmpty) return null;
    final payload = dataLines.join('\n');
    try {
      final decoded = jsonDecode(payload);
      if (decoded is Map<String, dynamic>) {
        return AgUiEvent.parse(decoded);
      }
    } catch (_) {
      // Malformed frame — surface a synthetic UnknownEvent for diagnostics.
      return UnknownEvent(type: '__parse_error__', raw: {'data': payload});
    }
    return null;
  }
}

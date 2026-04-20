import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

/// One event from an AG-UI SSE stream.
class AgUiEvent {
  final String type;
  final Map<String, dynamic> data;

  const AgUiEvent({required this.type, required this.data});

  factory AgUiEvent.fromJson(Map<String, dynamic> json) =>
      AgUiEvent(type: json['type'] as String, data: json);
}

/// Production-grade AG-UI SSE client with reconnect + Last-Event-ID resume.
///
/// Phase 3.2 upgrade over the Flutter template's hand-rolled parser:
///   * exponential backoff on connection loss
///   * Last-Event-ID header resumes from the last delivered event
///   * graceful cancellation via the returned stream
///
/// Usage:
///
///     final client = AgUiClient(dio: Dio());
///     final sub = client.connect(url: '/agent/run', body: payload).listen((ev) {
///       // handle ev
///     });
class AgUiClient {
  final Dio _dio;
  final Duration _initialBackoff;
  final Duration _maxBackoff;
  String? _lastEventId;

  AgUiClient({
    required Dio dio,
    Duration initialBackoff = const Duration(milliseconds: 500),
    Duration maxBackoff = const Duration(seconds: 30),
  })  : _dio = dio,
        _initialBackoff = initialBackoff,
        _maxBackoff = maxBackoff;

  /// Open the SSE stream. Events are emitted onto the returned stream;
  /// closing the subscription cancels the HTTP request.
  Stream<AgUiEvent> connect({
    required String url,
    required Map<String, dynamic> body,
  }) async* {
    var backoff = _initialBackoff;
    while (true) {
      try {
        await for (final ev in _openOnce(url: url, body: body)) {
          yield ev;
          backoff = _initialBackoff;
        }
        // Clean close from the server — exit without retry.
        return;
      } catch (_) {
        await Future<void>.delayed(backoff);
        backoff = Duration(
          milliseconds: (backoff.inMilliseconds * 2).clamp(
            _initialBackoff.inMilliseconds,
            _maxBackoff.inMilliseconds,
          ),
        );
      }
    }
  }

  Stream<AgUiEvent> _openOnce({
    required String url,
    required Map<String, dynamic> body,
  }) async* {
    final headers = <String, dynamic>{
      'accept': 'text/event-stream',
      if (_lastEventId != null) 'last-event-id': _lastEventId!,
    };
    final response = await _dio.post<ResponseBody>(
      url,
      data: body,
      options: Options(
        headers: headers,
        responseType: ResponseType.stream,
      ),
    );

    final stream = response.data!.stream;
    final buffer = StringBuffer();
    await for (final chunk in stream) {
      buffer.write(utf8.decode(chunk, allowMalformed: true));
      while (true) {
        final body = buffer.toString();
        final boundary = body.indexOf('\n\n');
        if (boundary < 0) break;
        final raw = body.substring(0, boundary);
        buffer.clear();
        buffer.write(body.substring(boundary + 2));

        final event = _parseEvent(raw);
        if (event != null) yield event;
      }
    }
  }

  AgUiEvent? _parseEvent(String raw) {
    String? dataPayload;
    for (final line in raw.split('\n')) {
      if (line.startsWith('data:')) {
        dataPayload = line.substring(5).trimLeft();
      } else if (line.startsWith('id:')) {
        _lastEventId = line.substring(3).trim();
      }
    }
    if (dataPayload == null || dataPayload.isEmpty) return null;
    try {
      final decoded = jsonDecode(dataPayload);
      if (decoded is Map<String, dynamic>) {
        return AgUiEvent.fromJson(decoded);
      }
    } catch (_) {
      // Malformed event payload — skip.
    }
    return null;
  }
}

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

/// Production-grade AG-UI SSE client.
///
/// Connects to an AG-UI agent endpoint over Server-Sent Events. Each `data:`
/// frame is parsed into a typed event by the caller-supplied [parser]. This
/// keeps the package agnostic of the concrete event union — generated apps
/// can ship their own `sealed class AgUiEvent` hierarchy and feed its
/// `parse(json)` factory in.
///
/// Beyond the raw SSE plumbing, the client adds:
///
///   * exponential-backoff reconnect when [reconnect] is enabled
///   * `Last-Event-ID` header resumes from the last delivered event id
///   * graceful cancellation via the returned stream
///   * a [runAgent] convenience that matches the deepagent backend's
///     `POST /agent/run` contract (threadId/runId/messages/state/forwardedProps)
///
/// Usage with a typed event union:
///
///     final client = AgUiClient<AgUiEvent>(
///       dio: Dio(),
///       parser: AgUiEvent.parse,
///       onParseError: (data) => UnknownEvent(type: '__parse_error__', raw: {'data': data}),
///     );
///     await for (final ev in client.runAgent(threadId: 't', runId: 'r', messages: [])) {
///       // handle ev
///     }
class AgUiClient<E> {
  final Dio _dio;
  final String _baseUrl;
  final E? Function(Map<String, dynamic>) _parser;
  final E? Function(String raw)? _onParseError;
  final bool _reconnect;
  final Duration _initialBackoff;
  final Duration _maxBackoff;
  String? _lastEventId;

  AgUiClient({
    required Dio dio,
    required E? Function(Map<String, dynamic>) parser,
    E? Function(String raw)? onParseError,
    String baseUrl = '/agent/',
    bool reconnect = false,
    Duration initialBackoff = const Duration(milliseconds: 500),
    Duration maxBackoff = const Duration(seconds: 30),
  })  : _dio = dio,
        _baseUrl = baseUrl,
        _parser = parser,
        _onParseError = onParseError,
        _reconnect = reconnect,
        _initialBackoff = initialBackoff,
        _maxBackoff = maxBackoff;

  /// Run an AG-UI agent against the deepagent `POST /agent/run` contract.
  ///
  /// Returns a one-shot stream that completes when the server closes the
  /// SSE connection or emits RUN_FINISHED. If [reconnect] was enabled at
  /// construction the stream resumes via Last-Event-ID on transient errors;
  /// otherwise a transport failure is surfaced via [onParseError] (if
  /// provided) and the stream closes.
  Stream<E> runAgent({
    required String threadId,
    required String runId,
    required List<Map<String, dynamic>> messages,
    Map<String, dynamic> state = const {},
    Map<String, dynamic> forwardedProps = const {},
    String? bearerToken,
  }) {
    final body = <String, dynamic>{
      'threadId': threadId,
      'runId': runId,
      'messages': messages,
      'state': state,
      'tools': const <Map<String, dynamic>>[],
      'context': const <Map<String, dynamic>>[],
      'forwardedProps': forwardedProps,
    };
    return connect(url: _baseUrl, body: body, bearerToken: bearerToken);
  }

  /// Open an SSE stream against an arbitrary URL.
  ///
  /// The body is JSON-encoded. Events are emitted onto the returned stream;
  /// closing the subscription cancels the HTTP request.
  Stream<E> connect({
    required String url,
    required Map<String, dynamic> body,
    String? bearerToken,
  }) async* {
    if (!_reconnect) {
      yield* _openOnce(url: url, body: body, bearerToken: bearerToken);
      return;
    }

    var backoff = _initialBackoff;
    while (true) {
      try {
        await for (final ev in _openOnce(url: url, body: body, bearerToken: bearerToken)) {
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

  Stream<E> _openOnce({
    required String url,
    required Map<String, dynamic> body,
    String? bearerToken,
  }) async* {
    final headers = <String, dynamic>{
      'Accept': 'text/event-stream',
      'Content-Type': 'application/json',
      if (_lastEventId != null) 'Last-Event-ID': _lastEventId!,
      if (bearerToken != null && bearerToken.isNotEmpty)
        'Authorization': 'Bearer $bearerToken',
    };

    Response<ResponseBody> response;
    try {
      response = await _dio.post<ResponseBody>(
        url,
        data: jsonEncode(body),
        options: Options(
          headers: headers,
          responseType: ResponseType.stream,
          receiveTimeout: const Duration(minutes: 10),
        ),
      );
    } on DioException {
      // Reconnect mode catches this in connect(); non-reconnect mode lets
      // onParseError surface a synthetic event and then closes.
      if (_reconnect) rethrow;
      final synthetic = _onParseError?.call('agent request failed');
      if (synthetic != null) yield synthetic;
      return;
    }

    final stream = response.data?.stream;
    if (stream == null) {
      final synthetic = _onParseError?.call('agent returned an empty stream');
      if (synthetic != null) yield synthetic;
      return;
    }

    final buffer = StringBuffer();
    await for (final chunk in stream.cast<List<int>>().transform(utf8.decoder)) {
      buffer.write(chunk);
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
  }

  E? _parseFrame(String frame) {
    final dataLines = <String>[];
    for (final line in const LineSplitter().convert(frame)) {
      if (line.startsWith('data:')) {
        dataLines.add(line.substring(5).trimLeft());
      } else if (line.startsWith('id:')) {
        _lastEventId = line.substring(3).trim();
      }
      // Comment lines (':' prefix) and blank lines are skipped.
    }
    if (dataLines.isEmpty) return null;
    final payload = dataLines.join('\n');
    try {
      final decoded = jsonDecode(payload);
      if (decoded is Map<String, dynamic>) {
        return _parser(decoded);
      }
    } catch (_) {
      return _onParseError?.call(payload);
    }
    return null;
  }
}

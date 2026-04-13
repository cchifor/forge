import 'dart:convert';

import 'package:{{project_slug}}/src/features/auth/data/jwt_decoder.dart';
import 'package:flutter_test/flutter_test.dart';

/// Builds a fake JWT with the given [payload] map.
String _buildJwt(Map<String, dynamic> payload) {
  final header = base64Url.encode(utf8.encode('{"alg":"HS256","typ":"JWT"}'));
  final body = base64Url.encode(utf8.encode(json.encode(payload)));
  const signature = 'fake-signature';
  return '$header.$body.$signature';
}

void main() {
  group('JwtDecoder.decode', () {
    test('decodes a valid JWT payload', () {
      final token = _buildJwt({'sub': '123', 'name': 'Test'});
      final claims = JwtDecoder.decode(token);
      expect(claims['sub'], '123');
      expect(claims['name'], 'Test');
    });

    test('decodes JWT with nested objects', () {
      final token = _buildJwt({
        'sub': 'u1',
        'realm_access': {
          'roles': ['admin'],
        },
      });
      final claims = JwtDecoder.decode(token);
      expect(claims['realm_access'], isA<Map<String, dynamic>>());
      expect(
        (claims['realm_access'] as Map)['roles'],
        contains('admin'),
      );
    });

    test('throws FormatException for token with fewer than 3 parts', () {
      expect(
        () => JwtDecoder.decode('only.two'),
        throwsA(isA<FormatException>()),
      );
    });

    test('throws FormatException for empty string', () {
      expect(
        () => JwtDecoder.decode(''),
        throwsA(isA<FormatException>()),
      );
    });

    test('throws for malformed base64 payload', () {
      // header.!!!invalid!!!.signature — three parts but bad base64
      expect(
        () => JwtDecoder.decode('aaa.!!!.ccc'),
        throwsA(isA<Exception>()),
      );
    });

    test('throws for payload that is not valid JSON', () {
      final badBody = base64Url.encode(utf8.encode('not json'));
      expect(
        () => JwtDecoder.decode('header.$badBody.sig'),
        throwsA(isA<FormatException>()),
      );
    });
  });
}

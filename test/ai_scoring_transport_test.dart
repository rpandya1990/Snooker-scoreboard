import 'dart:io';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:snooker_scoreboard/ai_scoring/client.dart';
import 'package:snooker_scoreboard/ai_scoring/coordinator.dart';

void main() {
  test('trusted LAN HTTP carries bearer and does not follow redirects',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    var requests = 0;
    final subscription = server.listen((request) async {
      requests++;
      expect(request.headers.value(HttpHeaders.authorizationHeader),
          'Bearer test-pairing');
      if (request.uri.path == '/redirect') {
        request.response.statusCode = 302;
        request.response.headers.set(HttpHeaders.locationHeader, '/unexpected');
      } else if (request.uri.path == '/failure') {
        request.response.statusCode = 400;
        request.response.write('secret-token rtsp://private-camera');
      } else {
        request.response.headers.contentType = ContentType.json;
        request.response.write('{"ok":true}');
      }
      await request.response.close();
    });
    addTearDown(() async {
      await subscription.cancel();
      await server.close(force: true);
    });
    final client = HttpObserverTransport(AiConfig(
        endpoint: 'http://127.0.0.1:${server.port}', token: 'test-pairing'));
    expect(await client.request('GET', '/ok', null), {'ok': true});
    await expectLater(
        client.request('GET', '/redirect', null), throwsStateError);
    await expectLater(
        client.request('GET', '/failure', null),
        throwsA(isA<ObserverTransportException>()
            .having((e) => e.reason, 'reason', ObserverFailure.httpResponse)
            .having((e) => e.status, 'status', 400)));
    expect(requests, 3);
  });
  test(
      'HTTP public hosts and missing bearer are rejected before any connection',
      () async {
    final public = HttpObserverTransport(
        const AiConfig(endpoint: 'http://example.com', token: 'test'));
    await expectLater(
        public.request('GET', '/v1/sessions', null), throwsStateError);
    final unauthenticated = HttpObserverTransport(
        const AiConfig(endpoint: 'http://127.0.0.1:1234'));
    await expectLater(
        unauthenticated.request('GET', '/v1/sessions', null), throwsStateError);
  });
  test('JSON POST declares exact UTF-8 Content-Length and never chunked',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final received = <List<int>>[];
    final subscription = server.listen((request) async {
      final bytes =
          await request.fold<List<int>>([], (all, part) => all..addAll(part));
      received.add(bytes);
      expect(request.contentLength, bytes.length);
      expect(request.contentLength, greaterThan(0));
      expect(request.headers.value(HttpHeaders.transferEncodingHeader), isNull);
      request.response.headers.contentType = ContentType.json;
      request.response.write('{"accepted":true}');
      await request.response.close();
    });
    addTearDown(() async {
      await subscription.cancel();
      await server.close(force: true);
    });
    final transport = HttpObserverTransport(AiConfig(
        endpoint: 'http://127.0.0.1:${server.port}', token: 'test-pairing'));
    final payload = {
      'sessionId': 'session',
      'mode': 'dry-run',
      'note': '黄球 🎱'
    };
    expect(await transport.request('POST', '/v1/sessions', payload),
        {'accepted': true});
    expect(received.single, utf8.encode(jsonEncode(payload)));
  });
}

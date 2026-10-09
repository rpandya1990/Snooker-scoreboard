import 'dart:io';
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
    expect(requests, 2);
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
}

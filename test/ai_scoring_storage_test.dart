import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:snooker_scoreboard/ai_scoring/client.dart';
import 'package:snooker_scoreboard/ai_scoring/coordinator.dart';

class ReplayTransport implements ObserverTransport {
  final List<Map<String, dynamic>> delivered = [];
  bool fail = true;
  @override
  Future<Map<String, dynamic>> request(
      String method, String path, Map<String, dynamic>? body) async {
    if (fail) throw StateError('offline');
    if (path.endsWith('/events')) delivered.add(Map.from(body!));
    return {};
  }
}

class LostStopAckTransport implements ObserverTransport {
  final Set<String> applied = {};
  final List<String> attempted = [];
  bool loseAck = true;
  @override
  Future<Map<String, dynamic>> request(
      String method, String path, Map<String, dynamic>? body) async {
    // Mirrors the companion contract: historical POST only returns metadata;
    // it never reopens capture, even when the original stop was acknowledged.
    if (path.endsWith('/events')) {
      final id = body!['eventId'] as String;
      attempted.add(id);
      applied.add(id);
      if (loseAck) {
        loseAck = false;
        throw StateError('accepted but ACK lost');
      }
    }
    return {'stopped': true};
  }
}

void main() {
  test(
      'restart retains unsent session on failure then retries original event exactly',
      () async {
    final root = await Directory.systemTemp.createTemp('observer-outbox-test');
    addTearDown(() => root.delete(recursive: true));
    const config = AiConfig(mode: AiMode.dryRun, cameraAlias: 'table');
    final old =
        JsonPendingStore('old-session', config, directory: () async => root);
    await old.save([
      {
        'eventId': 'original-id',
        'sequence': 5,
        'type': 'break_committed',
        'submittedPoints': 12
      }
    ]);
    final fresh =
        JsonPendingStore('new-session', config, directory: () async => root);
    final transport = ReplayTransport();
    await expectLater(fresh.replay(transport), throwsStateError);
    expect(
        await File('${root.path}/ai_scoring/old-session-pending.json')
            .readAsString(),
        contains('original-id'));
    transport.fail = false;
    await fresh.replay(transport);
    expect(transport.delivered.first['eventId'], 'original-id');
    expect(transport.delivered.last['type'], 'session_stopped');
    expect(transport.delivered.last['sequence'], 6);
    await fresh.replay(transport);
    expect(transport.delivered.length, 2);
  });
  test(
      'lost final stop ACK replays identical ID without generating another stop',
      () async {
    final root = await Directory.systemTemp.createTemp('observer-stop-retry');
    addTearDown(() => root.delete(recursive: true));
    const config = AiConfig(mode: AiMode.dryRun, cameraAlias: 'table');
    final old = JsonPendingStore('stopped-session', config,
        directory: () async => root);
    await old.save([
      {'eventId': 'stop-original', 'sequence': 6, 'type': 'session_stopped'}
    ]);
    final fresh =
        JsonPendingStore('new-session', config, directory: () async => root);
    final transport = LostStopAckTransport();
    await expectLater(fresh.replay(transport), throwsStateError);
    expect(
        await File('${root.path}/ai_scoring/stopped-session-pending.json')
            .readAsString(),
        contains('stop-original'));
    await fresh.replay(transport);
    expect(transport.attempted, ['stop-original', 'stop-original']);
    expect(transport.applied, {'stop-original'});
    await fresh.replay(transport);
    expect(transport.attempted.length, 2);
  });
}

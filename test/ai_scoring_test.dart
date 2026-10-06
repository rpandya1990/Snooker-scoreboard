import 'package:flutter_test/flutter_test.dart';
import 'package:snooker_scoreboard/ai_scoring/coordinator.dart';

class FakeTransport implements ObserverTransport {
  final List<Map<String, dynamic>> events = [];
  Map<String, dynamic> prediction = {};
  bool fail = false;
  @override
  Future<Map<String, dynamic>> request(
      String method, String path, Map<String, dynamic>? body) async {
    if (fail) throw StateError('offline');
    if (path.endsWith('/events')) events.add(body!);
    if (path.endsWith('/heartbeat'))
      return {'serverTimestamp': DateTime.now().toUtc().toIso8601String()};
    return path.endsWith('/prediction') ? prediction : {};
  }
}

class FakeStore implements PendingStore {
  List<Map<String, dynamic>> saved = [];
  bool fail = false;
  @override
  Future<void> save(List<Map<String, dynamic>> events) async {
    if (fail) throw StateError('disk full');
    saved = events;
  }
}

void main() {
  test('off performs no work or delivery', () async {
    final transport = FakeTransport();
    final store = FakeStore();
    final c =
        AiCoordinator(const AiConfig(), transport: transport, store: store);
    c.start();
    c.commit(c.freeze(), 12, 12);
    c.stop();
    await c.sync();
    expect(c.pending, isEmpty);
    expect(transport.events, isEmpty);
    expect(store.saved, isEmpty);
  });
  test(
      'offline entries keep identities, null freeze and submitted delta separately',
      () async {
    final transport = FakeTransport()..fail = true;
    final store = FakeStore();
    final c = AiCoordinator(const AiConfig(mode: AiMode.dryRun),
        transport: transport, store: store);
    c.start();
    await c.sync();
    final oldRun = c.runId;
    final attempt = c.freeze();
    c.commit(attempt, 15, 3);
    expect(c.runId, isNot(oldRun));
    final event = c.pending.last;
    expect(event['submittedPoints'], 15);
    expect(event['appliedScoreDelta'], 3);
    expect(event['predictionId'], isNull);
    expect(event['source'], 'manual');
    c.stop();
    await c.sync();
    expect(c.pending.map((e) => e['sequence']), [1, 2, 3]);
    await c.flushStorage();
    expect(store.saved.length, 3);
  });
  test('frozen prediction never replaced and AI edits retain source', () async {
    final transport = FakeTransport();
    final c = AiCoordinator(const AiConfig(mode: AiMode.assist),
        transport: transport, store: FakeStore());
    c.start();
    await Future<void>.delayed(Duration.zero);
    await c.sync();
    transport.prediction = {
      'predictionId': 'p1',
      'status': 'available',
      'points': 15,
      'frameId': c.frameId,
      'runId': c.runId,
      'lastAppliedEventSequence': 1,
      'observationEpoch': 'e1',
      'expiresAt': DateTime.now()
          .add(const Duration(minutes: 1))
          .toUtc()
          .toIso8601String()
    };
    await c.sync();
    final attempt = c.freeze();
    expect(attempt.points, 15);
    transport.prediction = {
      ...transport.prediction,
      'predictionId': 'p2',
      'points': 20
    };
    await c.sync();
    expect(attempt.points, 15);
    expect(c.canSuggest(attempt), isFalse);
    attempt.selected = true;
    attempt.edited = true;
    c.commit(attempt, 12, 12);
    c.stop();
    await Future<void>.delayed(Duration.zero);
    await c.sync();
    final entry =
        transport.events.firstWhere((e) => e['type'] == 'break_committed');
    expect(entry['predictionId'], 'p1');
    expect(entry['source'], 'ai_selected_edited');
  });
}

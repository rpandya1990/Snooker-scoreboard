import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:snooker_scoreboard/ai_scoring/coordinator.dart';
import 'package:snooker_scoreboard/pages/scoreboard_page.dart';

class WidgetObserverTransport implements ObserverTransport {
  final DateTime Function() clock;
  Map<String, dynamic> Function()? prediction;
  final List<Map<String, dynamic>> events = [];
  WidgetObserverTransport(this.clock);
  @override
  Future<Map<String, dynamic>> request(
      String method, String path, Map<String, dynamic>? body) async {
    if (path.endsWith('/events')) events.add(Map.from(body!));
    if (path.endsWith('/heartbeat'))
      return {'serverTimestamp': clock().toIso8601String()};
    return path.endsWith('/prediction') ? prediction!() : {};
  }
}

void main() {
  testWidgets('dry-run grouped taps, deduction undo keep one complete entry',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final observer = AiCoordinator(const AiConfig(mode: AiMode.dryRun));
    await tester.pumpWidget(MaterialApp(
        home: ScoreboardPage(
            player1Name: 'A', player2Name: 'B', observer: observer)));
    await tester.pump();
    expect(find.byIcon(Icons.auto_awesome), findsNothing);
    await tester.tap(find.byIcon(Icons.add).first);
    await tester.pump();
    await tester.tap(find.byIcon(Icons.add).first);
    await tester.pump();
    await tester.tap(find.byIcon(Icons.remove).first);
    await tester.pump();
    await tester.tap(find.byIcon(Icons.undo).first);
    await tester.pump();
    await tester.pump(const Duration(seconds: 6));
    final entries =
        observer.pending.where((e) => e['type'] == 'break_committed').toList();
    expect(entries.length, 1);
    expect(entries.single['submittedPoints'], 2);
    expect(entries.single['appliedScoreDelta'], 2);
    expect(entries.single['correctionAffected'], isTrue);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('cancel additive input emits no entry and no AI in dry-run',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final observer = AiCoordinator(const AiConfig(mode: AiMode.dryRun));
    await tester.pumpWidget(MaterialApp(
        home: ScoreboardPage(
            player1Name: 'A', player2Name: 'B', observer: observer)));
    await tester.pump();
    final state = tester.state(find.byType(ScoreboardPage)) as dynamic;
    state.openScoreInput(state.player1, true);
    await tester.pumpAndSettle();
    expect(find.byIcon(Icons.auto_awesome), findsNothing);
    Navigator.of(tester.element(find.byType(TextField))).pop();
    await tester.pumpAndSettle();
    expect(
        observer.pending.where((e) => e['type'] == 'break_committed'), isEmpty);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets(
      'assist fills frozen score, waits for Done and records edited mismatch',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final time = DateTime.utc(2026, 10, 5);
    final transport = WidgetObserverTransport(() => time);
    final observer = AiCoordinator(const AiConfig(mode: AiMode.assist),
        transport: transport, clock: () => time);
    transport.prediction = () => {
          'predictionId': 'frozen-15',
          'status': 'available',
          'points': 15,
          'frameId': observer.frameId,
          'runId': observer.runId,
          'lastAppliedEventSequence': 1,
          'observationEpoch': 'camera-epoch',
          'activityVersion': 1,
          'expiresAt': time.add(const Duration(minutes: 1)).toIso8601String()
        };
    await tester.pumpWidget(MaterialApp(
        home: ScoreboardPage(
            player1Name: 'A', player2Name: 'B', observer: observer)));
    await tester.pump();
    await observer.sync();
    final state = tester.state(find.byType(ScoreboardPage)) as dynamic;
    state.openScoreInput(state.player1, true);
    await tester.pumpAndSettle();
    expect(find.byIcon(Icons.auto_awesome), findsOneWidget);
    await tester.tap(find.byIcon(Icons.auto_awesome));
    await tester.pump();
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '15');
    expect(state.player1.score, 0);
    expect(
        transport.events.where((e) => e['type'] == 'break_committed'), isEmpty);
    await tester.enterText(find.byType(TextField), '12');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    await observer.sync();
    expect(state.player1.score, 12);
    final entries = [...transport.events, ...observer.pending]
        .where((e) => e['type'] == 'break_committed')
        .toList();
    expect(entries, hasLength(1));
    expect(entries.single['predictionId'], 'frozen-15');
    expect(entries.single['submittedPoints'], 12);
    expect(entries.single['source'], 'ai_selected_edited');
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('frozen suggestion expires while input stays manual and editable',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    var time = DateTime.utc(2026, 10, 5);
    final expires = time.add(const Duration(seconds: 5));
    final transport = WidgetObserverTransport(() => time);
    final observer = AiCoordinator(const AiConfig(mode: AiMode.assist),
        transport: transport, clock: () => time);
    transport.prediction = () => {
          'predictionId': 'expires',
          'status': 'available',
          'points': 15,
          'frameId': observer.frameId,
          'runId': observer.runId,
          'lastAppliedEventSequence': 1,
          'observationEpoch': 'camera-epoch',
          'activityVersion': 1,
          'expiresAt': expires.toIso8601String()
        };
    await tester.pumpWidget(MaterialApp(
        home: ScoreboardPage(
            player1Name: 'A', player2Name: 'B', observer: observer)));
    await tester.pump();
    await observer.sync();
    final state = tester.state(find.byType(ScoreboardPage)) as dynamic;
    state.openScoreInput(state.player1, true);
    await tester.pumpAndSettle();
    expect(find.byIcon(Icons.auto_awesome), findsOneWidget);
    time = time.add(const Duration(seconds: 10));
    await tester.pump(const Duration(seconds: 1));
    expect(find.byIcon(Icons.auto_awesome), findsNothing);
    await tester.enterText(find.byType(TextField), '9');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(state.player1.score, 9);
    final entries = [...transport.events, ...observer.pending]
        .where((e) => e['type'] == 'break_committed')
        .toList();
    expect(entries.single['source'], 'manual');
    expect(entries.single['predictionId'], 'expires');
    await tester.pumpWidget(const SizedBox());
  });
}

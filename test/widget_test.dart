import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:snooker_scoreboard/main.dart';
import 'package:snooker_scoreboard/pages/scoreboard_page.dart';

void main() {
  testWidgets('app loads and shows main menu options', (WidgetTester tester) async {
    await tester.pumpWidget(SnookerScoreboardApp());

    expect(find.text('Rated Match'), findsOneWidget);
    expect(find.text('Practice'), findsOneWidget);
    expect(find.text('Manage Players'), findsOneWidget);
    expect(find.text('Leaderboard'), findsOneWidget);
  });

  testWidgets('end frame button is disabled when both players are tied', (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: ScoreboardPage(
          player1Name: 'Raghav',
          player2Name: 'Carkey',
        ),
      ),
    );

    await tester.pumpAndSettle();

    final button = tester.widget<ElevatedButton>(
      find.widgetWithText(ElevatedButton, 'End Frame & Start New'),
    );

    expect(button.onPressed, isNull);
  });

  testWidgets('end frame button is enabled when scores differ', (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: ScoreboardPage(
          player1Name: 'Raghav',
          player2Name: 'Carkey',
        ),
      ),
    );

    await tester.pumpAndSettle();

    final state = tester.state(find.byType(ScoreboardPage)) as dynamic;
    state.player1.score = 10;
    state.player2.score = 4;
    state.setState(() {});
    await tester.pump();

    final button = tester.widget<ElevatedButton>(
      find.widgetWithText(ElevatedButton, 'End Frame & Start New'),
    );

    expect(button.onPressed, isNotNull);
  });
}

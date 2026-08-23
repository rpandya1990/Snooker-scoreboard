import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:snooker_scoreboard/main.dart';
import 'package:snooker_scoreboard/pages/scoreboard_page.dart';

void main() {
  testWidgets('scoreboard uses more available width on large landscape screens', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() => tester.view.resetPhysicalSize());

    await tester.pumpWidget(
      const MediaQuery(
        data: MediaQueryData(size: Size(1600, 900)),
        child: MaterialApp(
          home: ScoreboardPage(
            player1Name: 'Raghav',
            player2Name: 'Carkey',
          ),
        ),
      ),
    );

    final largeLandscapeConstraint = tester.widgetList<ConstrainedBox>(find.byType(ConstrainedBox)).any(
      (box) => box.constraints.maxWidth > 1400,
    );

    expect(largeLandscapeConstraint, isTrue);
  });

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
      find.widgetWithText(ElevatedButton, 'Finish Frame'),
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
      find.widgetWithText(ElevatedButton, 'Finish Frame'),
    );

    expect(button.onPressed, isNotNull);
  });
}

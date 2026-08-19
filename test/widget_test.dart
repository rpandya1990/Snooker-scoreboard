import 'package:flutter_test/flutter_test.dart';

import 'package:snooker_scoreboard/main.dart';

void main() {
  testWidgets('app loads and shows main menu options', (WidgetTester tester) async {
    await tester.pumpWidget(SnookerScoreboardApp());

    expect(find.text('Rated Match'), findsOneWidget);
    expect(find.text('Practice'), findsOneWidget);
    expect(find.text('Manage Players'), findsOneWidget);
    expect(find.text('Leaderboard'), findsOneWidget);
  });
}

import 'package:flutter/material.dart';
import 'player_selection_page.dart';
import 'manage_players_page.dart';
import 'leaderboard_page.dart';

class MainMenuPage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ElevatedButton(
              child: Text('Start Match'),
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => PlayerSelectionPage()),
                );
              },
            ),
            SizedBox(height: 16),
            ElevatedButton(
              child: Text('Manage Players'),
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => ManagePlayersPage()),
                );
              },
            ),
            SizedBox(height: 16),
            ElevatedButton(
              child: Text('Leaderboard'),
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => LeaderboardPage()),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

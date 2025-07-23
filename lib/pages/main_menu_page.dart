import 'package:flutter/material.dart';
import 'player_selection_page.dart';
import 'manage_players_page.dart';
import 'leaderboard_page.dart';

class MainMenuPage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final screenHeight = MediaQuery.of(context).size.height;

    // Smaller font size, clamped between 12 and 20
    final double fontSize = (screenWidth * 0.04).clamp(12, 20);

    // Fixed button size for all buttons
    final buttonWidth = screenWidth * 0.6; // 60% of screen width
    final buttonHeight = 50.0;

    final verticalSpacing = 16.0;

    return Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _buildMenuButton(
              context,
              text: 'Rated Match',
              fontSize: fontSize,
              width: buttonWidth,
              height: buttonHeight,
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => PlayerSelectionPage(isPractice: false),
                  ),
                );
              },
            ),
            SizedBox(height: verticalSpacing),
            _buildMenuButton(
              context,
              text: 'Practice',
              fontSize: fontSize,
              width: buttonWidth,
              height: buttonHeight,
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => PlayerSelectionPage(isPractice: true),
                  ),
                );
              },
            ),
            SizedBox(height: verticalSpacing),
            _buildMenuButton(
              context,
              text: 'Manage Players',
              fontSize: fontSize,
              width: buttonWidth,
              height: buttonHeight,
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => ManagePlayersPage()),
                );
              },
            ),
            SizedBox(height: verticalSpacing),
            _buildMenuButton(
              context,
              text: 'Leaderboard',
              fontSize: fontSize,
              width: buttonWidth,
              height: buttonHeight,
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

  Widget _buildMenuButton(BuildContext context,
      {required String text,
      required double fontSize,
      required double width,
      required double height,
      required VoidCallback onPressed}) {
    return SizedBox(
      width: width,
      height: height,
      child: ElevatedButton(
        onPressed: onPressed,
        child: Text(
          text,
          style: TextStyle(fontSize: fontSize),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

class LeaderboardPage extends StatefulWidget {
  @override
  _LeaderboardPageState createState() => _LeaderboardPageState();
}

class _LeaderboardPageState extends State<LeaderboardPage> {
  List<Map<String, dynamic>> leaderboardData = [];

  @override
  void initState() {
    super.initState();
    _loadLeaderboardData();
  }

  Future<void> _loadLeaderboardData() async {
    final prefs = await SharedPreferences.getInstance();
    final keys = prefs.getKeys();

    final playerNames = prefs.getStringList('playerNames') ?? [];

    List<Map<String, dynamic>> playerStats = [];

    for (var name in playerNames) {
      try {
        final rating = prefs.getInt('player_${name}_rating') ?? 1500;
        final framesWon = prefs.getInt('player_${name}_totalFramesWon') ?? 0;
        final framesLost = prefs.getInt('player_${name}_totalFramesLost') ?? 0;
        final maxBreak = prefs.getInt('player_${name}_cumulativeMaxBreak') ?? 0;

        playerStats.add({
          'name': name,
          'rating': rating,
          'framesWon': framesWon,
          'framesLost': framesLost,
          'maxBreak': maxBreak,
        });
      } catch (_) {
        // Skip bad entries
      }
    }

    playerStats.sort((a, b) => b['rating'].compareTo(a['rating']));

    setState(() {
      leaderboardData = playerStats.take(10).toList();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Leaderboard')),
      body: leaderboardData.isEmpty
          ? Center(child: Text('No data available'))
          : ListView.builder(
              itemCount: leaderboardData.length,
              itemBuilder: (context, index) {
                final player = leaderboardData[index];
                return Container(
                  color: index % 2 == 0 ? Colors.grey[100] : Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${index + 1}. ${player['name']}',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                      ),
                      const SizedBox(height: 4),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('Rating: ${player['rating']}'),
                          Text('Won: ${player['framesWon']}'),
                          Text('Lost: ${player['framesLost']}'),
                          Text('Max Break: ${player['maxBreak']}'),
                        ],
                      ),
                    ],
                  ),
                );
              },
            ),
    );
  }
}

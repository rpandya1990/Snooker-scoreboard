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
      } catch (e) {
        // Skip bad entries
      }
    }

    // Sort by rating and limit to top 10
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
          : LayoutBuilder(
              builder: (context, constraints) {
                return SingleChildScrollView(
                  padding: EdgeInsets.all(16),
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minWidth: constraints.maxWidth),
                    child: DataTable(
                      headingRowColor: MaterialStateProperty.resolveWith<Color?>(
                        (Set<MaterialState> states) => Colors.grey[300],
                      ),
                      columnSpacing: 24,
                      columns: const [
                        DataColumn(label: Expanded(child: Text('Name'))),
                        DataColumn(label: Expanded(child: Text('Rating'))),
                        DataColumn(label: Expanded(child: Text('Frames Won'))),
                        DataColumn(label: Expanded(child: Text('Frames Lost'))),
                        DataColumn(label: Expanded(child: Text('Max Break'))),
                      ],
                      rows: leaderboardData.map((player) {
                        return DataRow(cells: [
                          DataCell(Text(player['name'])),
                          DataCell(Text(player['rating'].toString())),
                          DataCell(Text(player['framesWon'].toString())),
                          DataCell(Text(player['framesLost'].toString())),
                          DataCell(Text(player['maxBreak'].toString())),
                        ]);
                      }).toList(),
                    ),
                  ),
                );
              },
            ),
    );
  }
}

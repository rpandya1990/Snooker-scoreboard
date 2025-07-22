import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'scoreboard_page.dart';

class PlayerSelectionPage extends StatefulWidget {
  @override
  _PlayerSelectionPageState createState() => _PlayerSelectionPageState();
}

class _PlayerSelectionPageState extends State<PlayerSelectionPage> {
  List<String> players = [];
  String? selectedPlayer1;
  String? selectedPlayer2;

  @override
  void initState() {
    super.initState();
    _loadPlayers();
  }

  Future<void> _loadPlayers() async {
    final prefs = await SharedPreferences.getInstance();
    final savedPlayers = prefs.getStringList('playerNames') ?? [];
    setState(() {
      players = savedPlayers;
      if (players.isNotEmpty) {
        selectedPlayer1 = players[0];
        selectedPlayer2 = players.length > 1 ? players[1] : players[0];
      }
    });
  }

  void _startMatch() {
    if (selectedPlayer1 == null || selectedPlayer2 == null) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Please select two players')));
      return;
    }
    if (selectedPlayer1 == selectedPlayer2) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Please select two different players')));
      return;
    }
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (_) => ScoreboardPage(
          player1Name: selectedPlayer1!,
          player2Name: selectedPlayer2!,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Select Players'),
      ),
      body: players.isEmpty
          ? Center(child: Text('No players found. Add players first.'))
          : Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  DropdownButtonFormField<String>(
                    decoration: InputDecoration(labelText: 'Player 1'),
                    value: selectedPlayer1,
                    items: players
                        .map((p) => DropdownMenuItem(
                              value: p,
                              child: Text(p),
                            ))
                        .toList(),
                    onChanged: (val) => setState(() => selectedPlayer1 = val),
                  ),
                  SizedBox(height: 16),
                  DropdownButtonFormField<String>(
                    decoration: InputDecoration(labelText: 'Player 2'),
                    value: selectedPlayer2,
                    items: players
                        .map((p) => DropdownMenuItem(
                              value: p,
                              child: Text(p),
                            ))
                        .toList(),
                    onChanged: (val) => setState(() => selectedPlayer2 = val),
                  ),
                  SizedBox(height: 32),
                  ElevatedButton(
                    onPressed: _startMatch,
                    child: Text('Start Match'),
                  ),
                ],
              ),
            ),
    );
  }
}

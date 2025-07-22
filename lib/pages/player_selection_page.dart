import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'scoreboard_page.dart';

class PlayerSelectionPage extends StatefulWidget {
  final bool isPractice; // optional, in case you want to forward this later

  PlayerSelectionPage({this.isPractice = false});

  @override
  _PlayerSelectionPageState createState() => _PlayerSelectionPageState();
}

class _PlayerSelectionPageState extends State<PlayerSelectionPage> {
  List<String> players = [];
  Set<String> selectedPlayers = {};

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
      // Preselect first two if available
      if (savedPlayers.length >= 2) {
        selectedPlayers = savedPlayers.take(2).toSet();
      } else {
        selectedPlayers = savedPlayers.toSet();
      }
    });
  }

  void _onPlayerTap(String playerName) {
    setState(() {
      if (selectedPlayers.contains(playerName)) {
        selectedPlayers.remove(playerName);
      } else {
        if (selectedPlayers.length < 2) {
          selectedPlayers.add(playerName);
        } else {
          // Optionally show a message that only 2 players can be selected
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('You can select only 2 players')),
          );
        }
      }
    });
  }

  void _startMatch() {
    if (selectedPlayers.length != 2) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Please select exactly two players')));
      return;
    }
    final selectedList = selectedPlayers.toList();

    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (_) => ScoreboardPage(
          player1Name: selectedList[0],
          player2Name: selectedList[1],
          isPractice: widget.isPractice,
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
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Select exactly 2 players:',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  SizedBox(height: 12),
                  Expanded(
                    child: ListView.builder(
                      itemCount: players.length,
                      itemBuilder: (context, index) {
                        final player = players[index];
                        final selected = selectedPlayers.contains(player);
                        return ListTile(
                          title: Text(player),
                          trailing: selected
                              ? Icon(Icons.check_box, color: Colors.teal)
                              : Icon(Icons.check_box_outline_blank),
                          onTap: () => _onPlayerTap(player),
                        );
                      },
                    ),
                  ),
                  SizedBox(height: 16),
                  Center(
                    child: ElevatedButton(
                      onPressed: _startMatch,
                      child: Text('Start Match'),
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}

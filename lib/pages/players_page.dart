import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'player.dart';

class PlayersPage extends StatefulWidget {
  final Function(String player1, String player2) onPlayersSelected;

  const PlayersPage({required this.onPlayersSelected, Key? key}) : super(key: key);

  @override
  _PlayersPageState createState() => _PlayersPageState();
}

class _PlayersPageState extends State<PlayersPage> {
  List<Player> players = [];
  TextEditingController _newPlayerController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadPlayers();
  }

  Future<void> _loadPlayers() async {
    final prefs = await SharedPreferences.getInstance();
    final names = prefs.getStringList('playerNames') ?? [];
    players = names
        .map((name) => Player(0, name))
        .toList(); // id is unused here, or can assign incrementally
    // Load stats for each player
    for (var player in players) {
      await player.
      (prefs);
    }
    setState(() {});
  }

  Future<void> _savePlayers() async {
    final prefs = await SharedPreferences.getInstance();
    final names = players.map((p) => p.name).toList();
    await prefs.setStringList('playerNames', names);
    // Save stats for all players as well
    for (var player in players) {
      await player.saveStats(prefs);
    }
  }

  void _addPlayer() {
    final name = _newPlayerController.text.trim();
    if (name.isEmpty) return;
    if (players.any((p) => p.name == name)) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Player with this name already exists')),
      );
      return;
    }
    setState(() {
      players.add(Player(0, name));
      _newPlayerController.clear();
    });
    _savePlayers();
  }

  void _showPlayerStats(Player player) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(player.name),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Max Break Ever: ${player.cumulativeMaxBreak}'),
            Text('Frames Won: ${player.totalFramesWon}'),
            Text('Frames Lost: ${player.totalFramesLost}'),
            Text('Rating: ${player.rating}'),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text('Close'),
          ),
        ],
      ),
    );
  }

  Widget _buildPlayerTile(Player player) {
    return ListTile(
      title: Text(player.name),
      onTap: () => _showPlayerStats(player),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Players'),
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              itemCount: players.length,
              itemBuilder: (context, index) => _buildPlayerTile(players[index]),
            ),
          ),
          Padding(
            padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _newPlayerController,
                    decoration: InputDecoration(
                      labelText: 'New player name',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                SizedBox(width: 8),
                ElevatedButton(
                  onPressed: _addPlayer,
                  child: Text('Add'),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(bottom: 12.0),
            child: ElevatedButton(
              onPressed: players.length < 2
                  ? null
                  : () {
                      widget.onPlayersSelected(players[0].name, players[1].name);
                    },
              child: Text('Start Match with First 2 Players'),
            ),
          )
        ],
      ),
    );
  }
}

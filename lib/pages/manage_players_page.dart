import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ManagePlayersPage extends StatefulWidget {
  @override
  _ManagePlayersPageState createState() => _ManagePlayersPageState();
}

class _ManagePlayersPageState extends State<ManagePlayersPage> {
  List<PlayerData> players = [];

  @override
  void initState() {
    super.initState();
    _loadPlayers();
  }

  Future<void> _loadPlayers() async {
    final prefs = await SharedPreferences.getInstance();
    final playerNames = prefs.getStringList('playerNames') ?? [];
    List<PlayerData> loadedPlayers = [];
    for (var name in playerNames) {
      final maxBreak = prefs.getInt('player_${name}_cumulativeMaxBreak') ?? 0;
      final framesWon = prefs.getInt('player_${name}_totalFramesWon') ?? 0;
      final framesLost = prefs.getInt('player_${name}_totalFramesLost') ?? 0;
      final rating = prefs.getInt('player_${name}_rating') ?? 1500;
      loadedPlayers.add(PlayerData(name, maxBreak, framesWon, framesLost, rating));
    }
    setState(() {
      players = loadedPlayers;
    });
  }

  Future<void> _addPlayer() async {
    final newName = await showDialog<String>(
      context: context,
      builder: (context) => AddPlayerDialog(),
    );
    if (newName != null && newName.trim().isNotEmpty) {
      final prefs = await SharedPreferences.getInstance();
      final playerNames = prefs.getStringList('playerNames') ?? [];
      if (!playerNames.contains(newName)) {
        playerNames.add(newName);
        await prefs.setStringList('playerNames', playerNames);
        await prefs.setInt('player_${newName}_cumulativeMaxBreak', 0);
        await prefs.setInt('player_${newName}_totalFramesWon', 0);
        await prefs.setInt('player_${newName}_totalFramesLost', 0);
        await prefs.setInt('player_${newName}_rating', 1500);
        await _loadPlayers();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Player "$newName" already exists.')),
        );
      }
    }
  }

  void _showPlayerStats(PlayerData player) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${player.name} - Statistics'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Rating: ${player.rating}'),
            Text('Max Break: ${player.maxBreak}'),
            Text('Frames Won: ${player.framesWon}'),
            Text('Frames Lost: ${player.framesLost}'),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: Text('Close'))
        ],
      ),
    );
  }

  void _confirmDeletePlayer(String playerName) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete Player'),
        content: Text('Are you sure you want to delete "$playerName"? This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: Text('Delete')),
        ],
      ),
    );
    if (confirmed == true) {
      final prefs = await SharedPreferences.getInstance();
      final playerNames = prefs.getStringList('playerNames') ?? [];
      playerNames.remove(playerName);
      await prefs.setStringList('playerNames', playerNames);
      await prefs.remove('player_${playerName}_cumulativeMaxBreak');
      await prefs.remove('player_${playerName}_totalFramesWon');
      await prefs.remove('player_${playerName}_totalFramesLost');
      await prefs.remove('player_${playerName}_rating');
      await _loadPlayers();
    }
  }

  Widget _buildActionMenu(PlayerData player) {
    return PopupMenuButton<String>(
      onSelected: (value) {
        if (value == 'delete') {
          _confirmDeletePlayer(player.name);
        }
      },
      itemBuilder: (context) => [
        PopupMenuItem<String>(
          value: 'delete',
          child: Text('Delete'),
        ),
      ],
      icon: Icon(Icons.more_vert),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Manage Players')),
      body: players.isEmpty
          ? Center(child: Text('No players added yet. Tap + to add a player.'))
          : LayoutBuilder(
              builder: (context, constraints) {
                return SingleChildScrollView(
                  padding: EdgeInsets.all(16),
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minWidth: constraints.maxWidth),
                    child: DataTable(
                      columnSpacing: 24,
                      headingRowColor: MaterialStateProperty.resolveWith<Color?>(
                        (Set<MaterialState> states) => Colors.grey[300],
                      ),
                      columns: const [
                        DataColumn(label: Expanded(child: Text('Player Name'))),
                        DataColumn(label: Expanded(child: Text('Stats'))),
                        DataColumn(label: Expanded(child: Text('Actions'))),
                      ],
                      rows: players.map((player) {
                        return DataRow(cells: [
                          DataCell(Text(player.name)),
                          DataCell(
                            IconButton(
                              icon: Icon(Icons.info_outline),
                              tooltip: 'View Stats',
                              onPressed: () => _showPlayerStats(player),
                            ),
                          ),
                          DataCell(_buildActionMenu(player)),
                        ]);
                      }).toList(),
                    ),
                  ),
                );
              },
            ),
      floatingActionButton: FloatingActionButton(
        onPressed: _addPlayer,
        child: Icon(Icons.add),
        tooltip: 'Add Player',
      ),
    );
  }
}

class PlayerData {
  final String name;
  final int maxBreak;
  final int framesWon;
  final int framesLost;
  final int rating;

  PlayerData(this.name, this.maxBreak, this.framesWon, this.framesLost, this.rating);
}

class AddPlayerDialog extends StatefulWidget {
  @override
  _AddPlayerDialogState createState() => _AddPlayerDialogState();
}

class _AddPlayerDialogState extends State<AddPlayerDialog> {
  final TextEditingController _controller = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: EdgeInsets.symmetric(horizontal: 40, vertical: 24),
      child: SingleChildScrollView(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _controller,
                autofocus: true,
                decoration: InputDecoration(
                  hintText: 'Enter player name',
                  border: OutlineInputBorder(),
                ),
              ),
              SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: Text('Cancel'),
                  ),
                  SizedBox(width: 8),
                  ElevatedButton(
                    onPressed: () {
                      final name = _controller.text.trim();
                      Navigator.pop(context, name.isEmpty ? null : name);
                    },
                    child: Text('Add'),
                  ),
                ],
              )
            ],
          ),
        ),
      ),
    );
  }
}

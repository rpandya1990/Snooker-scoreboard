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
  TextEditingController _searchController = TextEditingController();
  String _searchText = '';

  @override
  void initState() {
    super.initState();
    _loadPlayers();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadPlayers() async {
    final prefs = await SharedPreferences.getInstance();
    final savedPlayers = prefs.getStringList('playerNames') ?? [];
    setState(() {
      players = savedPlayers;
      if (savedPlayers.length >= 2) {
        selectedPlayers = savedPlayers.take(2).toSet();
      } else {
        selectedPlayers = savedPlayers.toSet();
      }
    });
  }

  List<String> get _filteredPlayers {
    final query = _searchText.trim().toLowerCase();
    if (query.isEmpty) return players;
    return players.where((player) => player.toLowerCase().contains(query)).toList();
  }

  void _resetSelection() {
    setState(() {
      selectedPlayers.clear();
      if (players.length >= 2) {
        selectedPlayers.addAll(players.take(2));
      } else {
        selectedPlayers.addAll(players);
      }
    });
  }

  void _onPlayerTap(String playerName) {
    setState(() {
      if (selectedPlayers.contains(playerName)) {
        selectedPlayers.remove(playerName);
        return;
      }

      if (selectedPlayers.length < 2) {
        selectedPlayers.add(playerName);
        return;
      }

      final firstSelected = selectedPlayers.toList().first;
      selectedPlayers.remove(firstSelected);
      selectedPlayers.add(playerName);

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Selected $playerName and replaced $firstSelected'),
          duration: Duration(seconds: 1),
        ),
      );
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
    final selectedList = selectedPlayers.toList();
    final filteredPlayers = _filteredPlayers;

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
                  SizedBox(height: 8),
                  if (selectedList.isNotEmpty)
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: selectedList.map((player) {
                        return InputChip(
                          label: Text(player),
                          selected: true,
                          onSelected: (_) => _onPlayerTap(player),
                          avatar: Icon(Icons.person),
                        );
                      }).toList(),
                    ),
                  SizedBox(height: 12),
                  TextField(
                    controller: _searchController,
                    decoration: InputDecoration(
                      hintText: 'Search players',
                      prefixIcon: Icon(Icons.search),
                      border: OutlineInputBorder(),
                      suffixIcon: _searchText.isNotEmpty
                          ? IconButton(
                              icon: Icon(Icons.clear),
                              onPressed: () {
                                _searchController.clear();
                                setState(() => _searchText = '');
                              },
                            )
                          : null,
                    ),
                    onChanged: (value) => setState(() => _searchText = value),
                  ),
                  SizedBox(height: 12),
                  Row(
                    children: [
                      TextButton.icon(
                        onPressed: _resetSelection,
                        icon: Icon(Icons.refresh),
                        label: Text('Reset'),
                      ),
                      Spacer(),
                      Text('${selectedPlayers.length}/2 selected'),
                    ],
                  ),
                  SizedBox(height: 8),
                  Expanded(
                    child: filteredPlayers.isEmpty
                        ? Center(child: Text('No players match your search'))
                        : ListView.builder(
                            itemCount: filteredPlayers.length,
                            itemBuilder: (context, index) {
                              final player = filteredPlayers[index];
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

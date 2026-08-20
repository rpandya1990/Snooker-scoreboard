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
    final screenWidth = MediaQuery.of(context).size.width;
    final screenHeight = MediaQuery.of(context).size.height;
    final isPhonePortrait = screenWidth < 600 && screenHeight >= screenWidth;

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        title: Text(
          'Select Players',
          style: TextStyle(
            fontSize: isPhonePortrait ? 30 : 26,
            fontWeight: FontWeight.w500,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, size: 30),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: players.isEmpty
          ? const Center(child: Text('No players found. Add players first.'))
          : SafeArea(
              child: Padding(
                padding: EdgeInsets.all(isPhonePortrait ? 14 : 16),
                child: ListView(
                  keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
                  children: [
                    Text(
                      'Select exactly 2 players:',
                      style: TextStyle(
                        fontSize: isPhonePortrait ? 26 : 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 12),
                    if (selectedList.isNotEmpty)
                      Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        children: selectedList.map((player) {
                          return SizedBox(
                            height: isPhonePortrait ? 44 : 42,
                            child: ChoiceChip(
                              label: Text(
                                player,
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              selected: true,
                              onSelected: (_) => _onPlayerTap(player),
                              selectedColor: Colors.red,
                              backgroundColor: Colors.red,
                              avatar: const Icon(Icons.person, color: Colors.white),
                              labelPadding: const EdgeInsets.symmetric(horizontal: 8),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                          );
                        }).toList(),
                      ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _searchController,
                      style: const TextStyle(fontSize: 20),
                      decoration: InputDecoration(
                        hintText: 'Search players',
                        hintStyle: TextStyle(
                          fontSize: isPhonePortrait ? 24 : 18,
                          color: const Color(0xFF0d8d8d),
                        ),
                        prefixIcon: const Icon(Icons.search, color: Color(0xFF0d8d8d), size: 30),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: const BorderSide(color: Color(0xFF0d8d8d), width: 2),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: const BorderSide(color: Color(0xFF0d8d8d), width: 2),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: const BorderSide(color: Color(0xFF0d8d8d), width: 2),
                        ),
                        contentPadding: const EdgeInsets.symmetric(vertical: 18, horizontal: 16),
                        suffixIcon: _searchText.isNotEmpty
                            ? IconButton(
                                icon: const Icon(Icons.clear, color: Color(0xFF0d8d8d)),
                                onPressed: () {
                                  _searchController.clear();
                                  setState(() => _searchText = '');
                                },
                              )
                            : null,
                      ),
                      onChanged: (value) => setState(() => _searchText = value),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        TextButton.icon(
                          onPressed: _resetSelection,
                          icon: const Icon(Icons.refresh),
                          label: const Text('Reset'),
                          style: TextButton.styleFrom(
                            foregroundColor: const Color(0xFF0d8d8d),
                          ),
                        ),
                        const Spacer(),
                        Text(
                          '${selectedPlayers.length}/2 selected',
                          style: TextStyle(
                            fontSize: isPhonePortrait ? 18 : 16,
                            fontWeight: FontWeight.w600,
                            color: Colors.black87,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    if (filteredPlayers.isEmpty)
                      const Center(child: Text('No players match your search'))
                    else
                      ListView.builder(
                        shrinkWrap: true,
                        physics: const NeverScrollableScrollPhysics(),
                        itemCount: filteredPlayers.length,
                        itemBuilder: (context, index) {
                          final player = filteredPlayers[index];
                          final selected = selectedPlayers.contains(player);
                          return Container(
                            margin: const EdgeInsets.only(bottom: 4),
                            decoration: BoxDecoration(
                              border: Border(
                                bottom: BorderSide(
                                  color: Colors.grey.shade200,
                                ),
                              ),
                            ),
                            child: ListTile(
                              contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                              title: Text(
                                player,
                                style: TextStyle(
                                  fontSize: isPhonePortrait ? 22 : 18,
                                ),
                              ),
                              trailing: selected
                                  ? const Icon(Icons.check_box, color: Colors.teal, size: 28)
                                  : const Icon(Icons.check_box_outline_blank, size: 28),
                              onTap: () => _onPlayerTap(player),
                            ),
                          );
                        },
                      ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: _startMatch,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF0d8d8d),
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14),
                          ),
                        ),
                        child: Text(
                          'Start Match',
                          style: TextStyle(
                            fontSize: isPhonePortrait ? 24 : 18,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}

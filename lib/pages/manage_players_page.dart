import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:file_picker/file_picker.dart';
import 'package:file_saver/file_saver.dart';

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

  Future<void> _exportPlayersToFile() async {
    if (players.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No players to export')),
      );
      return;
    }

    final prefs = await SharedPreferences.getInstance();
    final clubId = prefs.getString('clubId') ?? 'default_club';

    final exportPayload = {
      'schema': 'snooker_app_player_export',
      'version': 1,
      'clubId': clubId,
      'exportedAt': DateTime.now().toUtc().toIso8601String(),
      'players': players.map((p) => p.toJson()).toList(),
    };

    final jsonString = const JsonEncoder.withIndent('  ').convert(exportPayload);
    final bytes = Uint8List.fromList(utf8.encode(jsonString));
    final timestamp = DateTime.now()
      .toUtc()
      .toIso8601String()
      .replaceAll(':', '-')
      .replaceAll('.', '-');

    final fileName = 'snooker_players_${clubId}_$timestamp';

    try {
      await FileSaver.instance.saveFile(
        name: fileName,
        ext: 'json',
        bytes: bytes,
        mimeType: MimeType.json,
      );

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Exported as $fileName.json')),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to export: $e')),
      );
    }
  }

  Future<void> _importPlayersFromFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['json'],
        withData: true,
      );

      if (result == null || result.files.isEmpty) return;

      final file = result.files.single;
      final bytes = file.bytes;
      if (bytes == null) {
        throw const FormatException('No file data');
      }

      final content = utf8.decode(bytes);
      final decoded = jsonDecode(content);

      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Root JSON is not an object');
      }

      if (decoded['schema'] != 'snooker_app_player_export') {
        throw const FormatException('Unexpected schema');
      }

      final int version = (decoded['version'] as int?) ?? 1;
      if (version != 1) {
        throw FormatException('Unsupported version $version');
      }

      final String clubId =
          (decoded['clubId'] as String?) ?? 'default_club';

      final playersJson = decoded['players'] as List<dynamic>? ?? [];
      final importedPlayers = playersJson
        .map((e) => PlayerData.fromJson(e as Map<String, dynamic>))
        .toList();

      final prefs = await SharedPreferences.getInstance();

      // Clear old players from prefs
      final oldNames = prefs.getStringList('playerNames') ?? [];
      for (final name in oldNames) {
        await prefs.remove('player_${name}_cumulativeMaxBreak');
        await prefs.remove('player_${name}_totalFramesWon');
        await prefs.remove('player_${name}_totalFramesLost');
        await prefs.remove('player_${name}_rating');
      }

      // Save new players list
      final newNames = importedPlayers.map((p) => p.name).toList();
      await prefs.setStringList('playerNames', newNames);
      await prefs.setString('clubId', clubId);

      for (final p in importedPlayers) {
        await prefs.setInt(
          'player_${p.name}_cumulativeMaxBreak', p.maxBreak);
        await prefs.setInt(
          'player_${p.name}_totalFramesWon', p.framesWon);
        await prefs.setInt(
          'player_${p.name}_totalFramesLost', p.framesLost);
        await prefs.setInt('player_${p.name}_rating', p.rating);
      }

      setState(() {
        players = importedPlayers;
      });

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Players imported successfully')),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to import: $e')),
      );
    }
  }



  /// Export all players as a JSON blob that can be shared across tablets.
  Future<void> _exportPlayers() async {
    final prefs = await SharedPreferences.getInstance();

    // Future-friendly: a club identifier that can later map to a "club" entity.
    final clubId = prefs.getString('clubId') ?? 'default_club';

    final exportPayload = {
      'schema': 'snooker_app_player_export',
      'version': 1,
      'clubId': clubId,
      'exportedAt': DateTime.now().toUtc().toIso8601String(),
      'players': players.map((p) => p.toJson()).toList(),
    };

    final jsonString =
        const JsonEncoder.withIndent('  ').convert(exportPayload);

    await showDialog<void>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Export Players JSON'),
          content: SizedBox(
            width: double.maxFinite,
            child: SingleChildScrollView(
              child: SelectableText(
                jsonString,
                style: const TextStyle(fontFamily: 'monospace'),
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Close'),
            ),
          ],
        );
      },
    );
  }

  /// Import players from a JSON blob exported from another tablet / club.
  Future<void> _importPlayers() async {
    final input = await showDialog<String>(
      context: context,
      builder: (context) {
        final controller = TextEditingController();
        return AlertDialog(
          title: const Text('Import Players JSON'),
          content: SizedBox(
            width: double.maxFinite,
            child: TextField(
              controller: controller,
              maxLines: 12,
              decoration: const InputDecoration(
                hintText: 'Paste JSON exported from another device',
                border: OutlineInputBorder(),
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () =>
                  Navigator.of(context).pop(controller.text.trim()),
              child: const Text('Import'),
            ),
          ],
        );
      },
    );

    if (input == null || input.isEmpty) return;

    try {
      final decoded = jsonDecode(input);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Root JSON is not an object');
      }

      // Optional: validate schema & version for future evolution.
      if (decoded['schema'] != 'snooker_app_player_export') {
        throw const FormatException('Unexpected schema');
      }

      final int version = (decoded['version'] as int?) ?? 1;
      if (version != 1) {
        // For now we only know v1. You can add migrations here later.
        throw FormatException('Unsupported version $version');
      }

      final String clubId =
          (decoded['clubId'] as String?) ?? 'default_club';

      final playersJson = decoded['players'] as List<dynamic>? ?? [];
      final importedPlayers = playersJson
          .map((e) => PlayerData.fromJson(e as Map<String, dynamic>))
          .toList();

      final prefs = await SharedPreferences.getInstance();

      // Clear old players from prefs.
      final oldNames = prefs.getStringList('playerNames') ?? [];
      for (final name in oldNames) {
        await prefs.remove('player_${name}_cumulativeMaxBreak');
        await prefs.remove('player_${name}_totalFramesWon');
        await prefs.remove('player_${name}_totalFramesLost');
        await prefs.remove('player_${name}_rating');
      }

      // Save new players list.
      final newNames = importedPlayers.map((p) => p.name).toList();
      await prefs.setStringList('playerNames', newNames);
      await prefs.setString('clubId', clubId);

      for (final p in importedPlayers) {
        await prefs.setInt(
            'player_${p.name}_cumulativeMaxBreak', p.maxBreak);
        await prefs.setInt(
            'player_${p.name}_totalFramesWon', p.framesWon);
        await prefs.setInt(
            'player_${p.name}_totalFramesLost', p.framesLost);
        await prefs.setInt('player_${p.name}_rating', p.rating);
      }

      setState(() {
        players = importedPlayers;
      });

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Players imported successfully.')),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to import: $e')),
      );
    }
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
      appBar: AppBar(
        title: const Text('Manage Players'),
        actions: [
            IconButton(
              icon: const Icon(Icons.upload_file),
              tooltip: 'Export players to JSON file',
              onPressed: players.isEmpty ? null : _exportPlayersToFile,
            ),
            IconButton(
              icon: const Icon(Icons.download),
              tooltip: 'Import players from JSON file',
              onPressed: _importPlayersFromFile,
            ),
        ],
      ),
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

  PlayerData(
    this.name,
    this.maxBreak,
    this.framesWon,
    this.framesLost,
    this.rating,
  );

  Map<String, dynamic> toJson() => {
        'name': name,
        'maxBreak': maxBreak,
        'framesWon': framesWon,
        'framesLost': framesLost,
        'rating': rating,
      };

  factory PlayerData.fromJson(Map<String, dynamic> json) {
    return PlayerData(
      json['name'] as String,
      json['maxBreak'] as int? ?? 0,
      json['framesWon'] as int? ?? 0,
      json['framesLost'] as int? ?? 0,
      json['rating'] as int? ?? 1500,
    );
  }
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

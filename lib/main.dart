import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter/services.dart';
import 'package:audioplayers/audioplayers.dart';

final AudioPlayer _audioPlayer = AudioPlayer();

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.landscapeRight,
    DeviceOrientation.landscapeLeft,
  ]);
  runApp(SnookerScoreboardApp());
}

class SnookerScoreboardApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Snooker Scoreboard',
      theme: ThemeData(
        brightness: Brightness.light,
        scaffoldBackgroundColor: Colors.grey[200],
        textTheme: TextTheme(
          bodyMedium: TextStyle(color: Colors.black87, fontSize: 18),
        ),
        colorScheme: ColorScheme.light(
          primary: Colors.teal,
          secondary: Colors.red,
        ),
      ),
      home: ScoreboardPage(),
    );
  }
}

class Player {
  final int id; // 1 or 2
  final TextEditingController nameController;
  final FocusNode focusNode;

  int score = 0;
  int matchWins = 0;
  int maxBreakFrame = 0;
  int maxBreakSession = 0;

  int? _pendingAddStartScore;
  Timer? _addTimer;
  Timer? _blinkTimer;
  bool showScore = true;

  Player(this.id, String defaultName)
      : nameController = TextEditingController(text: defaultName),
        focusNode = FocusNode() {
    focusNode.addListener(() {
      if (!focusNode.hasFocus) {
        // Just for UI refresh if needed when editing completes
      }
    });
  }

  void dispose() {
    nameController.dispose();
    focusNode.dispose();
    _addTimer?.cancel();
    _blinkTimer?.cancel();
  }

  void startBlinking(VoidCallback updateUI) {
    _blinkTimer?.cancel();
    showScore = true;
    _blinkTimer = Timer.periodic(Duration(milliseconds: 500), (_) {
      showScore = !showScore;
      updateUI();
    });
  }

  void stopBlinking(VoidCallback updateUI) {
    _blinkTimer?.cancel();
    _blinkTimer = null;
    showScore = true;
    updateUI();
  }

  void finalizeAddBreak(VoidCallback updateUI) {
    if (_pendingAddStartScore == null) return;
    final breakPoints = score - _pendingAddStartScore!;
    if (breakPoints > maxBreakFrame) {
      maxBreakFrame = breakPoints;
      if (maxBreakFrame > maxBreakSession) {
        maxBreakSession = maxBreakFrame;
      }
    }
    _pendingAddStartScore = null;
    _addTimer?.cancel();
    _addTimer = null;
    stopBlinking(updateUI);
    updateUI();
  }

  void updateScoreByButton(int delta, VoidCallback updateUI) {
    score = (score + delta).clamp(0, 999);
    if (delta > 0) {
      if (_addTimer == null) {
        _pendingAddStartScore = score - delta;
      }
      _addTimer?.cancel();
      _addTimer = Timer(Duration(seconds: 5), () {
        finalizeAddBreak(updateUI);
      });
      startBlinking(updateUI);
    }
    updateUI();
  }

  void updateScoreWithBreak(int pointsAdded, VoidCallback updateUI) {
    if (pointsAdded <= 0) {
      score = (score + pointsAdded).clamp(0, 999);
      updateUI();
      return;
    }
    score = (score + pointsAdded).clamp(0, 999);
    if (pointsAdded > maxBreakFrame) {
      maxBreakFrame = pointsAdded;
      if (maxBreakFrame > maxBreakSession) {
        maxBreakSession = maxBreakFrame;
      }
    }
    updateUI();
  }

  void setScoreWithBreak(int newScore, VoidCallback updateUI) {
    score = newScore.clamp(0, 999);
    if (newScore > maxBreakFrame) {
      maxBreakFrame = newScore;
      if (maxBreakFrame > maxBreakSession) {
        maxBreakSession = maxBreakFrame;
      }
    }
    updateUI();
  }

  void cancelPendingTimers() {
    _addTimer?.cancel();
    _blinkTimer?.cancel();
    _addTimer = null;
    _blinkTimer = null;
    _pendingAddStartScore = null;
    showScore = true;
  }

  Future<void> saveToPrefs(SharedPreferences prefs) async {
    prefs.setInt('scoreP$id', score);
    prefs.setInt('matchWinsP$id', matchWins);
    prefs.setInt('maxBreakFrameP$id', maxBreakFrame);
    prefs.setInt('maxBreakSessionP$id', maxBreakSession);
    prefs.setString('playerName$id', nameController.text);
  }

  void loadFromPrefs(SharedPreferences prefs) {
    score = prefs.getInt('scoreP$id') ?? 0;
    matchWins = prefs.getInt('matchWinsP$id') ?? 0;
    maxBreakFrame = prefs.getInt('maxBreakFrameP$id') ?? 0;
    maxBreakSession = prefs.getInt('maxBreakSessionP$id') ?? 0;
    nameController.text = prefs.getString('playerName$id') ?? nameController.text;
  }
}

class ScoreboardPage extends StatefulWidget {
  @override
  _ScoreboardPageState createState() => _ScoreboardPageState();
}

class _ScoreboardPageState extends State<ScoreboardPage> {
  late Player player1;
  late Player player2;

  @override
  void initState() {
    super.initState();
    player1 = Player(1, 'Player 1');
    player2 = Player(2, 'Player 2');
    _loadData();
  }

  @override
  void dispose() {
    player1.dispose();
    player2.dispose();
    super.dispose();
  }

  void _saveData() async {
    final prefs = await SharedPreferences.getInstance();
    await player1.saveToPrefs(prefs);
    await player2.saveToPrefs(prefs);
  }

  void _loadData() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      player1.loadFromPrefs(prefs);
      player2.loadFromPrefs(prefs);
    });
  }

  void startNewFrame() async {
    await _audioPlayer.play(AssetSource('sounds/frame_end.mp3'));

    setState(() {
      if (player1.score > player2.score) player1.matchWins++;
      else if (player2.score > player1.score) player2.matchWins++;
      player1.score = 0;
      player2.score = 0;
      player1.maxBreakFrame = 0;
      player2.maxBreakFrame = 0;
      player1.cancelPendingTimers();
      player2.cancelPendingTimers();
      _saveData();
    });
  }

  void resetAll() {
    setState(() {
      player1.score = 0;
      player2.score = 0;
      player1.matchWins = 0;
      player2.matchWins = 0;
      player1.maxBreakFrame = 0;
      player2.maxBreakFrame = 0;
      player1.maxBreakSession = 0;
      player2.maxBreakSession = 0;
      player1.cancelPendingTimers();
      player2.cancelPendingTimers();
      _saveData();
    });
  }

  void openScoreInput(Player player, bool isUpdate) async {
    final points = await showModalBottomSheet<int>(
      context: context,
      isScrollControlled: true,
      builder: (context) => PointDialog(),
    );
    if (points != null) {
      setState(() {
        if (isUpdate == false) {
          player.setScoreWithBreak(points, () => setState(() {}));
        } else {
          player.updateScoreWithBreak(points, () => setState(() {}));
        }
        _saveData();
      });
    }
  }

  Widget scoreCard(Player player) {
    return Expanded(
      child: GestureDetector(
        onTap: () => openScoreInput(player, true),
        child: Card(
          margin: EdgeInsets.all(8),
          color: Colors.grey[850],
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                TextField(
                  controller: player.nameController,
                  focusNode: player.focusNode,
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: Colors.white),
                  decoration: InputDecoration(border: InputBorder.none),
                  onEditingComplete: () => player.focusNode.unfocus(),
                ),
                SizedBox(height: 10),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Opacity(
                      opacity: player.showScore ? 1.0 : 0.0,
                      child: Text(
                        player.score.toString(),
                        style: TextStyle(fontSize: 48, fontWeight: FontWeight.bold, color: Colors.white),
                      ),
                    ),
                    SizedBox(width: 8),
                    Text(
                      "(${player.matchWins})",
                      style: TextStyle(fontSize: 24, fontWeight: FontWeight.w500, color: Colors.grey[400]),
                    ),
                    SizedBox(width: 12),
                    IconButton(
                      icon: Icon(Icons.edit, color: Colors.tealAccent),
                      onPressed: () => openScoreInput(player, false),
                      tooltip: "Edit score",
                    ),
                  ],
                ),
                SizedBox(height: 6),
                Text(
                  "Max Break: ${player.maxBreakFrame} (${player.maxBreakSession})",
                  style: TextStyle(color: Colors.orangeAccent, fontWeight: FontWeight.w600),
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    IconButton(
                      onPressed: () => setState(() {
                        player.updateScoreByButton(1, () => setState(() {}));
                        _saveData();
                      }),
                      icon: Icon(Icons.add, color: Colors.greenAccent),
                    ),
                    IconButton(
                      onPressed: () => setState(() {
                        player.updateScoreByButton(-1, () => setState(() {}));
                        _saveData();
                      }),
                      icon: Icon(Icons.remove, color: Colors.redAccent),
                    ),
                  ],
                )
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // appBar: AppBar(title: Text('Snooker Scoreboard')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              Row(
                children: [
                  scoreCard(player1),
                  scoreCard(player2),
                ],
              ),
              SizedBox(height: 10),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                    ElevatedButton(onPressed: startNewFrame, child: Text("End Frame & Start New")),
                    ElevatedButton(onPressed: resetAll, child: Text("Reset")),
                ]
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class PointDialog extends StatefulWidget {
  @override
  _PointDialogState createState() => _PointDialogState();
}

class _PointDialogState extends State<PointDialog> {
  final TextEditingController _controller = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text("Enter Points"),
      content: TextField(
        controller: _controller,
        keyboardType: TextInputType.number,
        decoration: InputDecoration(hintText: "e.g. 4 or 0"),
        autofocus: true,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, int.tryParse(_controller.text)),
          child: Text('OK'),
        )
      ],
    );
  }
}

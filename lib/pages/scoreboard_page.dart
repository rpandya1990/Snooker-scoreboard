import 'dart:async';
import 'dart:math'; // Make sure this is at the top of your file
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:audioplayers/audioplayers.dart';
import 'player.dart';

final AudioPlayer _audioPlayer = AudioPlayer();

class ScoreboardPage extends StatefulWidget {
  final String player1Name;
  final String player2Name;
  final bool isPractice; // <-- New flag

  const ScoreboardPage({
    required this.player1Name,
    required this.player2Name,
    this.isPractice = false,  // default false for regular match
    Key? key,
  }) : super(key: key);

  @override
  _ScoreboardPageState createState() => _ScoreboardPageState();
}

class _ScoreboardPageState extends State<ScoreboardPage> {
  late Player player1;
  late Player player2;

  @override
  void initState() {
    super.initState();
    player1 = Player(1, widget.player1Name);
    player2 = Player(2, widget.player2Name);
    _loadPlayerStats();
  }

  Future<void> _loadPlayerStats() async {
    final prefs = await SharedPreferences.getInstance();
    await player1.loadStats(prefs);
    await player2.loadStats(prefs);
    setState(() {});
  }

  @override
  void dispose() {
    player1.dispose();
    player2.dispose();
    super.dispose();
  }

  Future<bool> _onWillPop() async {
    return await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text('Confirm Exit'),
            content: Text('Are you sure you want to exit? Your progress will be lost.'),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(false), // Don't exit
                child: Text('Cancel'),
              ),
              TextButton(
                onPressed: () => Navigator.of(context).pop(true), // Exit
                child: Text('Exit'),
              ),
            ],
          ),
        ) ??
        false;
  }

  void startNewFrame() async {
    await _audioPlayer.play(AssetSource('sounds/frame_end.mp3'));
    setState(() {
      _updatePlayerFrameStats();
      player1.score = 0;
      player2.score = 0;
      player1.maxBreakFrame = 0;
      player2.maxBreakFrame = 0;
      player1.cancelPendingTimers();
      player2.cancelPendingTimers();
    });
  }

 void _updatePlayerFrameStats() async {
   final breakWinner = player1.maxBreakFrame > player2.maxBreakFrame ? player1 : player2;
   final breakLoser = breakWinner == player1 ? player2 : player1;

   const int kFactor = 16;

   Player? frameWinner;
   Player? frameLoser;

   if (player1.score > player2.score) {
     player1.matchWins++;
     player1.totalFramesWon++;
     player2.totalFramesLost++;
     frameWinner = player1;
     frameLoser = player2;
   } else if (player2.score > player1.score) {
     player2.matchWins++;
     player2.totalFramesWon++;
     player1.totalFramesLost++;
     frameWinner = player2;
     frameLoser = player1;
   }

   if (frameWinner != null && frameLoser != null) {
     double expectedWinner = 1 / (1 + pow(10, (frameLoser.rating - frameWinner.rating) / 400));
     double expectedLoser = 1 / (1 + pow(10, (frameWinner.rating - frameLoser.rating) / 400));

     if (!widget.isPractice) {
       // Only update rating if NOT practice
       frameWinner.rating += (kFactor * (1 - expectedWinner)).round();
       frameLoser.rating += (kFactor * (0 - expectedLoser)).round();
     }
   }

   if (!widget.isPractice) {
     // Only update overall max break if NOT practice
     if (player1.maxBreakFrame > player1.cumulativeMaxBreak) {
       player1.cumulativeMaxBreak = player1.maxBreakFrame;
     }
     if (player2.maxBreakFrame > player2.cumulativeMaxBreak) {
       player2.cumulativeMaxBreak = player2.maxBreakFrame;
     }

     if (player1.maxBreakFrame != player2.maxBreakFrame) {
       breakWinner.rating += 2;
       breakLoser.rating -= 1;
     }

     player1.rating = player1.rating.clamp(1000, 3000);
     player2.rating = player2.rating.clamp(1000, 3000);
   }

   if (!widget.isPractice) {
     final prefs = await SharedPreferences.getInstance();
     await player1.saveStats(prefs);
     await player2.saveStats(prefs);
   }
 }


  void resetAll() {
    setState(() {
      player1.score = 0;
      player2.score = 0;
      player1.maxBreakFrame = 0;
      player2.maxBreakFrame = 0;
      player1.maxBreakSession = 0;
      player2.maxBreakSession = 0;
      player1.cancelPendingTimers();
      player2.cancelPendingTimers();
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
        if (!isUpdate) {
          player.setScoreWithBreak(points, isUpdate, () => setState(() {}));
        } else {
          player.updateScoreWithBreak(points, () => setState(() {}));
        }
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
                Text(
                  '${player.name} (${player.rating})',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: Colors.white),
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
                  "Max Break: ${player.maxBreakFrame} (${player.maxBreakSession}), Overall: ${player.cumulativeMaxBreak}",
                  style: TextStyle(color: Colors.orangeAccent, fontWeight: FontWeight.w600),
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    IconButton(
                      onPressed: () => setState(() {
                        player.updateScoreByButton(1, () => setState(() {}));
                      }),
                      icon: Icon(Icons.add, color: Colors.greenAccent),
                    ),
                    IconButton(
                      onPressed: () => setState(() {
                        player.updateScoreByButton(-1, () => setState(() {}));
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
    return WillPopScope(
      onWillPop: _onWillPop,
      child: Scaffold(
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
                  ],
                ),
              ],
            ),
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

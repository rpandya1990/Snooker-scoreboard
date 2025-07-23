import 'dart:async';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:audioplayers/audioplayers.dart';
import 'player.dart';

final AudioPlayer _audioPlayer = AudioPlayer();

class ScoreboardPage extends StatefulWidget {
  final String player1Name;
  final String player2Name;
  final bool isPractice;

  const ScoreboardPage({
    required this.player1Name,
    required this.player2Name,
    this.isPractice = false,
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
                onPressed: () => Navigator.of(context).pop(false),
                child: Text('Cancel'),
              ),
              TextButton(
                onPressed: () => Navigator.of(context).pop(true),
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
        frameWinner.rating += (kFactor * (1 - expectedWinner)).round();
        frameLoser.rating += (kFactor * (0 - expectedLoser)).round();
      }
    }

    if (!widget.isPractice) {
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

  Widget mergedScoreCard(Player p1, Player p2) {
    final screenWidth = MediaQuery.of(context).size.width;
    final screenHeight = MediaQuery.of(context).size.height;
    final isTablet = screenWidth > 600;

    // Scale factors
    double tabletScale = 0.65;
    double phoneScale = 0.4;

    // Dynamic sizes with scale factors
    double nameFontSize = isTablet
        ? screenWidth * 0.045 * tabletScale
        : screenWidth * 0.025 * phoneScale;
    double scoreFontSize = isTablet
        ? screenWidth * 0.12 * tabletScale
        : screenWidth * 0.04 * phoneScale;
    double labelFontSize = isTablet
        ? screenWidth * 0.035 * tabletScale
        : screenWidth * 0.015 * phoneScale;
    double iconSize = isTablet
        ? screenWidth * 0.06 * tabletScale
        : screenWidth * 0.025 * phoneScale;
    double padding = isTablet
        ? screenWidth * 0.03 * tabletScale
        : screenWidth * 0.0075 * phoneScale;

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
      children: [p1, p2].map((player) {
        return Expanded(
          child: Card(
            color: Colors.grey[900],
            margin: EdgeInsets.all(padding),
            child: Padding(
              padding: EdgeInsets.symmetric(
                vertical: padding * 1.2,
                horizontal: padding,
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    '${player.name} (${player.rating})',
                    style: TextStyle(
                      fontSize: nameFontSize,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  SizedBox(height: padding * 0.5),
                  GestureDetector(
                    onTap: () => openScoreInput(player, true),
                    child: Opacity(
                      opacity: player.showScore ? 1.0 : 0.0,
                      child: Text(
                        '${player.score}(${player.matchWins})',
                        style: TextStyle(
                          fontSize: scoreFontSize,
                          fontWeight: FontWeight.bold,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  ),
                  SizedBox(height: padding * 0.5),
                  Text(
                    "Break: ${player.maxBreakFrame} (${player.maxBreakSession}), Overall: ${player.cumulativeMaxBreak}",
                    style: TextStyle(
                      fontSize: labelFontSize,
                      color: Colors.orangeAccent,
                      fontWeight: FontWeight.w600,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  SizedBox(height: padding * 0.5),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      IconButton(
                        iconSize: iconSize,
                        icon: Icon(Icons.add, color: Colors.greenAccent),
                        onPressed: () {
                          setState(() {
                            player.updateScoreByButton(1, () => setState(() {}));
                          });
                        },
                      ),
                      IconButton(
                        iconSize: iconSize,
                        icon: Icon(Icons.remove, color: Colors.redAccent),
                        onPressed: () {
                          setState(() {
                            player.updateScoreByButton(-1, () => setState(() {}));
                          });
                        },
                      ),
                      IconButton(
                        iconSize: iconSize,
                        icon: Icon(Icons.edit, color: Colors.tealAccent),
                        onPressed: () => openScoreInput(player, false),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }




  @override
  Widget build(BuildContext context) {
    return WillPopScope(
      onWillPop: _onWillPop,
      child: Scaffold(
        backgroundColor: Colors.black,
        body: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                mergedScoreCard(player1, player2),
                SizedBox(height: 10),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    ElevatedButton(
                      onPressed: startNewFrame,
                      child: Text("End Frame & Start New"),
                    ),
                    ElevatedButton(
                      onPressed: resetAll,
                      child: Text("Reset"),
                    ),
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

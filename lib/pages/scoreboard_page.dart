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

class _ScoreAction {
  final Player player;
  final int previousScore;
  final int previousMaxBreakFrame;
  final int previousMaxBreakSession;
  final int previousCumulativeMaxBreak;
  final List<int> previousLastBreaks;

  _ScoreAction({
    required this.player,
    required this.previousScore,
    required this.previousMaxBreakFrame,
    required this.previousMaxBreakSession,
    required this.previousCumulativeMaxBreak,
    required this.previousLastBreaks,
  });
}


class _ScoreboardPageState extends State<ScoreboardPage> {
  late Player player1;
  late Player player2;

  // History for undo: last score change only
  final List<_ScoreAction> _history = [];

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

  Future<void> _confirmEndFrameAndStartNew() async {
    final frameWinner = player1.score > player2.score
        ? player1.name
        : player2.score > player1.score
            ? player2.name
            : 'Draw';

    final result = await showDialog<bool>(
      context: context,
      builder: (context) {
        final media = MediaQuery.of(context);
        final isCompactLandscape = media.size.width > media.size.height && media.size.width < 700;

        return AlertDialog(
          insetPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
          title: Text(
            'End frame and start new?',
            style: TextStyle(
              fontSize: isCompactLandscape ? 24 : 32,
              fontWeight: FontWeight.w600,
            ),
          ),
          content: ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: isCompactLandscape ? 420 : 520,
              maxHeight: media.size.height * 0.7,
            ),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Please confirm the frame summary before starting a new one.',
                    style: TextStyle(fontSize: isCompactLandscape ? 16 : 18),
                  ),
                  const SizedBox(height: 12),
                  Text('${player1.name}: ${player1.score}'),
                  Text('${player2.name}: ${player2.score}'),
                  const SizedBox(height: 8),
                  Text('${player1.name} max break: ${player1.maxBreakFrame}'),
                  Text('${player2.name} max break: ${player2.maxBreakFrame}'),
                  const SizedBox(height: 8),
                  Text(
                    'Frame winner: $frameWinner',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Confirm'),
            ),
          ],
        );
      },
    );

    if (result != true) return;

    await _audioPlayer.play(AssetSource('sounds/frame_end.mp3'));
    setState(() {
      _updatePlayerFrameStats();

      _history.clear();

      player1.score = 0;
      player2.score = 0;
      player1.maxBreakFrame = 0;
      player2.maxBreakFrame = 0;

      player1.lastBreaks.clear();
      player2.lastBreaks.clear();

      player1.cancelPendingTimers();
      player2.cancelPendingTimers();
    });
  }

  Future<void> _confirmFinishSession() async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Finish session?'),
        content: const Text(
          'Return to the main menu? The current session will end here.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Finish'),
          ),
        ],
      ),
    );

    if (result == true) {
      Navigator.of(context).pop();
    }
  }

  void _pushHistory(Player player) {
    _history.add(
      _ScoreAction(
        player: player,
        previousScore: player.score,
        previousMaxBreakFrame: player.maxBreakFrame,
        previousMaxBreakSession: player.maxBreakSession,
        previousCumulativeMaxBreak: player.cumulativeMaxBreak,
        previousLastBreaks: List<int>.from(player.lastBreaks),
      ),
    );
  }

  void _undoLastActionFor(Player player) {
    if (_history.isEmpty) return;

    // Find the last action for this specific player
    final actionIndex = _history.lastIndexWhere((a) => a.player == player);
    if (actionIndex == -1) {
      return; // no history for this player
    }

    final last = _history.removeAt(actionIndex);

    setState(() {
      last.player.score = last.previousScore;
      last.player.maxBreakFrame = last.previousMaxBreakFrame;
      last.player.maxBreakSession = last.previousMaxBreakSession;
      last.player.cumulativeMaxBreak = last.previousCumulativeMaxBreak;

      last.player.lastBreaks
        ..clear()
        ..addAll(last.previousLastBreaks);

      // Also cancel any blinking/timers for this player
      last.player.cancelPendingTimers();
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
      _history.clear();

      player1.score = 0;
      player2.score = 0;
      player1.maxBreakFrame = 0;
      player2.maxBreakFrame = 0;
      player1.maxBreakSession = 0;
      player2.maxBreakSession = 0;

      player1.lastBreaks.clear();
      player2.lastBreaks.clear();

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
        _pushHistory(player);

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
    final isLandscape = screenWidth > screenHeight;
    final isTablet = screenWidth > 700;
    final isPhoneLandscape = screenWidth >= 600 && screenWidth < 900 && isLandscape;
    final isLargeLandscape = isLandscape && screenWidth >= 1200;
    final sizeScale = isLargeLandscape ? 1.18 : (isTablet ? 1.08 : 1.0);

    Widget buildPlayerCard(Player player) {
      final recentBreaks = player.lastBreaks.reversed.take(3).toList();
      final breakText = recentBreaks.isEmpty
          ? 'Last breaks: –'
          : 'Last breaks: ${recentBreaks.join(', ')}';

      final cardPadding = isTablet ? 16.0 : (isPhoneLandscape ? 6.0 : 12.0);
      final titleSize = (isTablet
          ? (isLandscape ? 32.0 : 28.0)
          : isPhoneLandscape
              ? 16.0
              : isLandscape
                  ? 22.0
                  : 20.0) * sizeScale;
      final scoreSize = (isTablet
          ? (isLandscape ? 94.0 : 78.0)
          : isPhoneLandscape
              ? 50.0
              : isLandscape
                  ? 52.0
                  : 48.0) * sizeScale;
      final metaSize = (isTablet
          ? (isLandscape ? 19.0 : 17.0)
          : isPhoneLandscape
              ? 10.5
              : isLandscape
                  ? 13.5
                  : 12.5) * sizeScale;
      final iconSize = (isTablet ? 34.0 : (isPhoneLandscape ? 22.0 : 28.0)) * sizeScale;
      final cardMinHeight = isPhoneLandscape ? 150.0 : isLandscape ? 280.0 * sizeScale : 210.0;

      final content = Padding(
        padding: EdgeInsets.all(cardPadding),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '${player.name} (${player.rating})',
              style: TextStyle(
                fontSize: titleSize,
                fontWeight: FontWeight.bold,
                color: Colors.white,
              ),
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 8),
            GestureDetector(
              onTap: () => openScoreInput(player, true),
              child: Opacity(
                opacity: player.showScore ? 1.0 : 0.0,
                child: Text(
                  '${player.score}(${player.matchWins})',
                  style: TextStyle(
                    fontSize: scoreSize,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              breakText,
              style: TextStyle(
                fontSize: metaSize,
                color: Colors.white70,
              ),
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 6),
            Text(
              'Break: ${player.maxBreakFrame} (${player.maxBreakSession}), Overall: ${player.cumulativeMaxBreak}',
              style: TextStyle(
                fontSize: metaSize,
                color: Colors.orangeAccent,
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 8),
            Wrap(
              alignment: WrapAlignment.center,
              spacing: 8,
              runSpacing: 6,
              children: [
                IconButton(
                  iconSize: iconSize,
                  icon: const Icon(Icons.add, color: Colors.greenAccent),
                  onPressed: () {
                    setState(() {
                      if (!player.hasPendingBreak) {
                        _pushHistory(player);
                      }
                      player.updateScoreByButton(1, () => setState(() {}));
                    });
                  },
                ),
                IconButton(
                  iconSize: iconSize,
                  icon: const Icon(Icons.remove, color: Colors.redAccent),
                  onPressed: () {
                    setState(() {
                      _pushHistory(player);
                      player.updateScoreByButton(-1, () => setState(() {}));
                    });
                  },
                ),
                IconButton(
                  iconSize: iconSize,
                  icon: const Icon(Icons.edit, color: Colors.tealAccent),
                  onPressed: () => openScoreInput(player, false),
                ),
                IconButton(
                  iconSize: iconSize,
                  icon: const Icon(Icons.undo, color: Colors.amberAccent),
                  onPressed: _history.any((a) => a.player == player)
                      ? () => _undoLastActionFor(player)
                      : null,
                  tooltip: 'Undo last for ${player.name}',
                ),
              ],
            ),
          ],
        ),
      );

      return ConstrainedBox(
        constraints: BoxConstraints(minHeight: cardMinHeight),
        child: SizedBox(
          width: isLandscape ? null : double.infinity,
          child: Card(
            color: Colors.grey[900],
            margin: EdgeInsets.all(isLandscape ? 8 : 6),
            child: content,
          ),
        ),
      );
    }

    if (!isLandscape) {
      return Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(width: double.infinity, child: buildPlayerCard(p1)),
          SizedBox(width: double.infinity, child: buildPlayerCard(p2)),
        ],
      );
    }

    if (screenWidth < 760 && !isPhoneLandscape) {
      return Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(width: double.infinity, child: buildPlayerCard(p1)),
          SizedBox(width: double.infinity, child: buildPlayerCard(p2)),
        ],
      );
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(child: buildPlayerCard(p1)),
        Expanded(child: buildPlayerCard(p2)),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final screenHeight = MediaQuery.of(context).size.height;
    final isLandscape = screenWidth > screenHeight;
    final isPhone = screenWidth < 600;
    final isPhoneLandscape = isPhone && isLandscape;
    final isLargeLandscape = isLandscape && screenWidth >= 1200;
    final useStackedActions = isPhone && !isLandscape;
    final canEndFrame = player1.score != player2.score;

    final endFrameButton = ElevatedButton(
      onPressed: canEndFrame ? _confirmEndFrameAndStartNew : null,
      child: const Text('Finish Frame'),
    );

    final finishSessionButton = ElevatedButton(
      onPressed: _confirmFinishSession,
      child: const Text('Finish Session'),
    );

    final resetButton = ElevatedButton(
      onPressed: resetAll,
      child: const Text('Reset'),
    );

    final actionButtons = <Widget>[
      endFrameButton,
      if (finishSessionButton != null) finishSessionButton,
      resetButton,
    ];

    Widget actionLayout() {
      if (isPhoneLandscape) {
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SizedBox(width: 170, child: endFrameButton),
            const SizedBox(width: 8),
            SizedBox(width: 160, child: finishSessionButton),
            const SizedBox(width: 8),
            SizedBox(width: 110, child: resetButton),
          ],
        );
      }

      if (!useStackedActions) {
        return Wrap(
          alignment: WrapAlignment.center,
          spacing: 10,
          runSpacing: 10,
          children: actionButtons,
        );
      }

      return Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(width: double.infinity, child: endFrameButton),
          const SizedBox(height: 8),
          SizedBox(width: double.infinity, child: finishSessionButton),
          const SizedBox(height: 8),
          SizedBox(width: double.infinity, child: resetButton),
        ],
      );
    }

    return WillPopScope(
      onWillPop: _onWillPop,
      child: Scaffold(
        backgroundColor: Colors.black,
        body: isPhoneLandscape
            ? SafeArea(
                top: false,
                bottom: false,
                child: Center(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8.0, vertical: 0),
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 1400),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          mergedScoreCard(player1, player2),
                          const SizedBox(height: 2),
                          actionLayout(),
                        ],
                      ),
                    ),
                  ),
                ),
              )
            : SafeArea(
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    return ListView(
                      padding: EdgeInsets.all(isLandscape ? 12 : 16),
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        Center(
                          child: ConstrainedBox(
                            constraints: BoxConstraints(
                              maxWidth: isLargeLandscape ? max(screenWidth * 0.95, 1400.0) : 1400,
                            ),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                mergedScoreCard(player1, player2),
                                const SizedBox(height: 12),
                                actionLayout(),
                              ],
                            ),
                          ),
                        ),
                      ],
                    );
                  },
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

  void _submit() {
    final int? value = int.tryParse(_controller.text);
    if (value != null) {
      Navigator.pop(context, value);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text("Enter Points"),
      content: TextField(
        controller: _controller,
        keyboardType: TextInputType.number,
        autofocus: true,
        decoration: InputDecoration(
          hintText: "e.g. 4 or 0",
          border: OutlineInputBorder(), // bordered box
          contentPadding: EdgeInsets.symmetric(vertical: 12, horizontal: 12),
        ),
        textInputAction: TextInputAction.done,
        onSubmitted: (_) => _submit(), // submit on Done pressed
      ),
      // No actions (OK button removed)
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }
}

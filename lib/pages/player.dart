import 'package:flutter/material.dart';
import 'dart:async';
import 'package:shared_preferences/shared_preferences.dart';

class Player {
  final int id;
  final String name;

  bool get hasPendingBreak => _pendingAddStartScore != null;
  List<int> lastBreaks = [];
  int score = 0;
  int matchWins = 0;
  int maxBreakFrame = 0;
  int maxBreakSession = 0;
  int rating = 1500;

  // New cumulative stats
  int cumulativeMaxBreak = 0;
  int totalFramesWon = 0;
  int totalFramesLost = 0;

  int? _pendingAddStartScore;
  Timer? _addTimer;
  Timer? _blinkTimer;
  bool showScore = true;

  Player(this.id, this.name);
  
  Future<void> loadStats(SharedPreferences prefs) async {
    cumulativeMaxBreak = prefs.getInt('player_${name}_cumulativeMaxBreak') ?? 0;
    totalFramesWon = prefs.getInt('player_${name}_totalFramesWon') ?? 0;
    totalFramesLost = prefs.getInt('player_${name}_totalFramesLost') ?? 0;
    rating = prefs.getInt('player_${name}_rating') ?? 1500;
  }

  Future<void> saveStats(SharedPreferences prefs) async {
    await prefs.setInt('player_${name}_cumulativeMaxBreak', cumulativeMaxBreak);
    await prefs.setInt('player_${name}_totalFramesWon', totalFramesWon);
    await prefs.setInt('player_${name}_totalFramesLost', totalFramesLost);
    await prefs.setInt('player_${name}_rating', rating);
  }

  void dispose() {
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
    // Track this break
    _recordBreak(breakPoints);

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

    // Track this break
    _recordBreak(pointsAdded);

    updateUI();
  }

  void setScoreWithBreak(int newScore, bool isUpdate, VoidCallback updateUI) {
    score = newScore.clamp(0, 999);
    if (isUpdate && newScore > maxBreakFrame) {
      maxBreakFrame = newScore;
      if (maxBreakFrame > maxBreakSession) {
        maxBreakSession = maxBreakFrame;
      }
    }
    updateUI();
  }

  void _recordBreak(int points) {
      if (points <= 0) return;
      lastBreaks.add(points);
      if (lastBreaks.length > 3) {
        // Keep only the last 3
        lastBreaks.removeAt(0);
      }
    }

  void cancelPendingTimers() {
    _addTimer?.cancel();
    _blinkTimer?.cancel();
    _addTimer = null;
    _blinkTimer = null;
    _pendingAddStartScore = null;
    showScore = true;
  }

}

import 'dart:async';
import 'dart:math';
import 'dart:convert';

enum AiMode { off, dryRun, assist }

class AiConfig {
  final AiMode mode;
  final String endpoint, token;
  const AiConfig({this.mode = AiMode.off, this.endpoint = '', this.token = ''});
  factory AiConfig.environment() {
    const mode = String.fromEnvironment('AI_SCORING_MODE', defaultValue: 'off');
    return AiConfig(
        mode: mode == 'assist'
            ? AiMode.assist
            : mode == 'dry-run'
                ? AiMode.dryRun
                : AiMode.off,
        endpoint: const String.fromEnvironment('AI_SCORING_ENDPOINT'),
        token: const String.fromEnvironment('AI_SCORING_TOKEN'));
  }
}

abstract class ObserverTransport {
  Future<Map<String, dynamic>> request(
      String method, String path, Map<String, dynamic>? body);
}

abstract class RecoverablePendingStore {
  Future<void> replay(ObserverTransport transport);
}

abstract class PendingStore {
  Future<void> save(List<Map<String, dynamic>> events);
}

String observerId() {
  final random = Random.secure();
  return List.generate(
      16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}

class InputAttempt {
  final String id = observerId();
  final String entryId = observerId();
  final DateTime startedAt;
  final DateTime clientStartedAt;
  final Duration? clockOffset, clockUncertainty;
  final Map<String, dynamic>? prediction;
  final String unavailableReason;
  bool selected = false;
  bool edited = false;
  bool correctionAffected = false;
  int submitted = 0;
  InputAttempt(this.startedAt, this.prediction, this.unavailableReason,
      {DateTime? clientStartedAt, this.clockOffset, this.clockUncertainty})
      : clientStartedAt = clientStartedAt ?? startedAt;
  int? get points => prediction?['points'] as int?;
}

/// Owns observer identities and immutable pre-input comparisons; never local scores.
class AiCoordinator {
  final AiConfig config;
  final ObserverTransport? transport;
  final PendingStore? store;
  final DateTime Function() now;
  final String sessionId;
  String frameId = observerId(), runId = observerId();
  int _sequence = 0;
  Duration? _clockOffset;
  Duration? _clockUncertainty;
  bool _started = false;
  bool _opened = false, _stopped = false, _healthy = true, _busy = false;
  Map<String, dynamic>? _prediction;
  final List<Map<String, dynamic>> _pending = [];
  Future<void> _storage = Future.value();
  Timer? _timer;
  AiCoordinator(this.config,
      {this.transport,
      this.store,
      String? sessionId,
      DateTime Function()? clock})
      : sessionId = sessionId ?? observerId(),
        now = clock ?? DateTime.now;
  bool get enabled => config.mode != AiMode.off;
  bool get assist => config.mode == AiMode.assist;
  List<Map<String, dynamic>> get pending => List.unmodifiable(_pending);

  void start() {
    if (!enabled || _started) return;
    _started = true;
    _event('frame_started', {'frameId': frameId, 'runId': runId});
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => sync());
    sync();
  }

  InputAttempt freeze() {
    final p = _prediction;
    final valid = _healthy &&
        p != null &&
        p['status'] == 'available' &&
        p['frameId'] == frameId &&
        p['runId'] == runId &&
        p['lastAppliedEventSequence'] == _sequence &&
        p['points'] is int &&
        _clockOffset != null &&
        _clockUncertainty != null &&
        DateTime.tryParse(p['expiresAt']?.toString() ?? '')?.isAfter(
                now().toUtc().add(_clockOffset!).add(_clockUncertainty!)) ==
            true;
    final clientTime = now().toUtc();
    return InputAttempt(
        clientTime.add(_clockOffset ?? Duration.zero),
        valid
            ? Map.unmodifiable(
                jsonDecode(jsonEncode(p)) as Map<String, dynamic>)
            : null,
        valid ? '' : 'unavailable_or_unsynchronised',
        clientStartedAt: clientTime,
        clockOffset: _clockOffset,
        clockUncertainty: _clockUncertainty);
  }

  bool canSuggest(InputAttempt attempt) =>
      assist &&
      attempt.prediction != null &&
      _healthy &&
      attempt.prediction!['frameId'] == frameId &&
      attempt.prediction!['runId'] == runId &&
      _clockOffset != null &&
      _clockUncertainty != null &&
      DateTime.tryParse(attempt.prediction!['expiresAt']?.toString() ?? '')
              ?.isAfter(
                  now().toUtc().add(_clockOffset!).add(_clockUncertainty!)) ==
          true &&
      _prediction?['status'] == 'available' &&
      _prediction?['points'] == attempt.points &&
      _prediction?['observationEpoch'] ==
          attempt.prediction!['observationEpoch'] &&
      _prediction?['lastAppliedEventSequence'] == _sequence &&
      attempt.prediction!['activityVersion'] != null &&
      _prediction?['activityVersion'] == attempt.prediction!['activityVersion'];
  void commit(InputAttempt attempt, int submitted, int applied) {
    if (!enabled) return;
    final next = observerId();
    _event('break_committed', {
      'frameId': frameId,
      'runId': runId,
      'nextRunId': next,
      'entryId': attempt.entryId,
      'attemptId': attempt.id,
      'inputStartedAt': attempt.startedAt.toIso8601String(),
      'committedAt': now()
          .toUtc()
          .add(attempt.clockOffset ?? Duration.zero)
          .toIso8601String(),
      'clientInputStartedAt': attempt.clientStartedAt.toIso8601String(),
      'clientCommittedAt': now().toUtc().toIso8601String(),
      'clockOffsetMs': attempt.clockOffset?.inMicroseconds == null
          ? null
          : attempt.clockOffset!.inMicroseconds / 1000,
      'clockUncertaintyMs': attempt.clockUncertainty?.inMicroseconds == null
          ? null
          : attempt.clockUncertainty!.inMicroseconds / 1000,
      'predictionId': attempt.prediction?['predictionId'],
      'predictionAvailability':
          attempt.prediction == null ? attempt.unavailableReason : 'available',
      'submittedPoints': submitted,
      'appliedScoreDelta': applied,
      'source': attempt.selected
          ? (attempt.edited ? 'ai_selected_edited' : 'ai_selected')
          : 'manual',
      'correctionAffected': attempt.correctionAffected
    });
    runId = next;
    _prediction = null;
  }

  void correction(String? entryId, int submitted, int applied,
      {bool undo = false}) {
    if (!enabled) return;
    _event(undo ? 'undo' : 'correction', {
      'frameId': frameId,
      'runId': runId,
      'entryId': entryId,
      'affectedEntryIds': entryId == null ? [] : [entryId],
      'submittedPoints': submitted,
      'appliedScoreDelta': applied
    });
  }

  void newFrame() {
    if (!enabled) return;
    _event('frame_ended', {'frameId': frameId, 'runId': runId});
    frameId = observerId();
    runId = observerId();
    _prediction = null;
    _event('frame_started', {'frameId': frameId, 'runId': runId});
  }

  void stop() {
    if (!enabled || _stopped) return;
    _timer?.cancel();
    _prediction = null;
    _event('session_stopped', {'frameId': frameId, 'runId': runId});
    _stopped = true;
    sync();
  }

  void _event(String type, Map<String, dynamic> fields) {
    _pending.add({
      'eventId': observerId(),
      'sequence': ++_sequence,
      'type': type,
      'timestamp': now().toUtc().toIso8601String(),
      ...fields
    });
    _save();
    sync();
  }

  Future<void> flushStorage() => _storage;
  void _save() {
    final snapshot = _pending.map((e) => Map<String, dynamic>.from(e)).toList();
    _storage = _storage.then((_) async {
      try {
        await store?.save(snapshot);
      } catch (_) {
        _healthy = false;
        _prediction = null;
      }
    });
  }

  Future<void> sync() async {
    if (!enabled || _busy || transport == null) return;
    _busy = true;
    try {
      await _storage;
      if (!_opened) {
        if (store is RecoverablePendingStore)
          await (store as RecoverablePendingStore).replay(transport!);
        await transport!.request('POST', '/v1/sessions', {
          'sessionId': sessionId,
          'mode': config.mode == AiMode.assist ? 'assist' : 'dry-run'
        });
        _opened = true;
      }
      while (_pending.isNotEmpty) {
        final event = _pending.first;
        await transport!
            .request('POST', '/v1/sessions/$sessionId/events', event);
        _pending.removeAt(0);
        _save();
      }
      if (!_stopped) {
        final sent = now().toUtc();
        final heartbeat = await transport!.request(
            'POST',
            '/v1/sessions/$sessionId/heartbeat',
            {'clientTimestamp': sent.toIso8601String()});
        final received = now().toUtc();
        final server =
            DateTime.tryParse(heartbeat['serverTimestamp']?.toString() ?? '');
        final roundTrip = received.difference(sent);
        // No trusted clock measurement means no suggestions; manual collection continues.
        if (server != null && roundTrip <= const Duration(seconds: 1)) {
          _clockOffset = server.difference(
              sent.add(Duration(microseconds: roundTrip.inMicroseconds ~/ 2)));
          _clockUncertainty =
              Duration(microseconds: roundTrip.inMicroseconds ~/ 2);
        } else {
          _clockOffset = null;
          _clockUncertainty = null;
        }

        final p = await transport!
            .request('GET', '/v1/sessions/$sessionId/prediction', null);
        if (!_stopped) _prediction = p;
      }
    } catch (_) {
      _prediction = null;
      _opened = false;
    } finally {
      _busy = false;
    }
  }
}

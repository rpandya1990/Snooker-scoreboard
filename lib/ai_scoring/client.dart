import 'dart:convert';
import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'coordinator.dart';

bool _isLanHost(String host) {
  if (host.toLowerCase().endsWith('.local')) return true;
  final address = InternetAddress.tryParse(host);
  if (address == null) return false;
  if (address.isLoopback) return true;
  final bytes = address.rawAddress;
  if (address.type == InternetAddressType.IPv4) {
    return bytes[0] == 10 ||
        (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
        (bytes[0] == 192 && bytes[1] == 168);
  }
  return (bytes[0] & 0xfe) == 0xfc ||
      (bytes[0] == 0xfe && (bytes[1] & 0xc0) == 0x80);
}

class HttpObserverTransport implements ObserverTransport {
  final AiConfig config;
  final HttpClient _client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 3);
  HttpObserverTransport(this.config);
  @override
  Future<Map<String, dynamic>> request(
      String method, String path, Map<String, dynamic>? body) async {
    final base = Uri.parse(config.endpoint);
    if ((base.scheme != 'https' && base.scheme != 'http') ||
        (base.scheme == 'http' && !_isLanHost(base.host)) ||
        base.userInfo.isNotEmpty ||
        config.token.isEmpty) {
      throw StateError(
          'Observer requires HTTPS or authenticated local-network HTTP');
    }
    final request = await _client
        .openUrl(method, base.resolve(path))
        .timeout(const Duration(seconds: 3));
    request.followRedirects = false;
    request.headers
        .set(HttpHeaders.authorizationHeader, 'Bearer ${config.token}');
    request.headers.contentType = ContentType.json;
    if (body != null) request.write(jsonEncode(body));
    final response = await request.close().timeout(const Duration(seconds: 3));
    if (response.statusCode < 200 || response.statusCode >= 300)
      throw StateError('Observer unavailable');
    final text = await utf8.decoder
        .bind(response)
        .join()
        .timeout(const Duration(seconds: 3));
    return text.isEmpty
        ? {}
        : Map<String, dynamic>.from(jsonDecode(text) as Map);
  }
}

/// One file per observer session. Prior-process queues are delivered before new
/// collection opens; failures retain those files for retry, never overwrite them.
class JsonPendingStore implements PendingStore, RecoverablePendingStore {
  final String sessionId;
  final AiConfig config;
  final Future<Directory> Function()? directory;
  JsonPendingStore(this.sessionId, this.config, {this.directory});
  Future<Directory> _folder() async {
    final root = await (directory?.call() ?? getApplicationSupportDirectory());
    final folder = Directory('${root.path}/ai_scoring');
    await folder.create(recursive: true);
    return folder;
  }

  @override
  Future<void> save(List<Map<String, dynamic>> events) async {
    final folder = await _folder();
    await _write(File('${folder.path}/$sessionId-pending.json'), {
      'sessionId': sessionId,
      'mode': config.mode == AiMode.assist ? 'assist' : 'dry-run',
      'events': events
    });
  }

  Future<void> _write(File file, Map<String, dynamic> data) async {
    final temp = File('${file.path}.tmp');
    await temp.writeAsString(jsonEncode(data), flush: true);
    await temp.rename(file.path);
  }

  @override
  Future<void> replay(ObserverTransport transport) async {
    final folder = await _folder();
    final files = await folder
        .list()
        .where((e) =>
            e is File &&
            e.path.endsWith('-pending.json') &&
            !e.path.endsWith('/$sessionId-pending.json'))
        .toList();
    for (final entity in files) {
      final file = entity as File;
      final data = Map<String, dynamic>.from(
          jsonDecode(await file.readAsString()) as Map);
      // Legacy aliases describe old configuration, not camera selection.
      data.remove('cameraAlias');
      final events = (data['events'] as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
      if (events.isEmpty) continue;
      final oldId = data['sessionId'] as String;
      // Reopening only delivers metadata. The observer must report a restart gap;
      // Flutter never resumes that frame or requests its prediction.
      await transport.request(
          'POST', '/v1/sessions', {'sessionId': oldId, 'mode': data['mode']});
      if (events.last['type'] != 'session_stopped') {
        events.add({
          'eventId': observerId(),
          'sequence': (events.last['sequence'] as int) + 1,
          'type': 'session_stopped',
          'timestamp': DateTime.now().toUtc().toIso8601String(),
          'reason': 'app_process_restart'
        });
        data['events'] = events;
        await _write(file, data);
      }
      while (events.isNotEmpty) {
        await transport.request(
            'POST', '/v1/sessions/$oldId/events', events.first);
        events.removeAt(0);
        data['events'] = events;
        await _write(file, data);
      }
    }
  }
}

AiCoordinator createObserver() {
  final config = AiConfig.environment();
  if (config.mode == AiMode.off) return AiCoordinator(config);
  final id = observerId();
  return AiCoordinator(config,
      sessionId: id,
      transport: HttpObserverTransport(config),
      store: JsonPendingStore(id, config));
}

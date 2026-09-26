import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import '../services/backend_config.dart';


class ZoneTipData {
  final int zoneId;
  final String zoneName;
  final String borough;
  final double expectedTipUsd;

  const ZoneTipData({
    required this.zoneId,
    required this.zoneName,
    required this.borough,
    required this.expectedTipUsd,
  });

  factory ZoneTipData.fromJson(Map<String, dynamic> j) => ZoneTipData(
    zoneId: j['zone_id'] as int,
    zoneName: j['zone_name'] as String,
    borough: j['borough'] as String,
    expectedTipUsd: (j['expected_tip_usd'] as num).toDouble(),
  );
}

class TipPredictionsService {
  static final TipPredictionsService _instance =
      TipPredictionsService._internal();
  factory TipPredictionsService() => _instance;
  TipPredictionsService._internal();

  static const _fileName = 'tip_predictions.json';

  Future<File> _getCacheFile() async {
    final dir = await getApplicationDocumentsDirectory();
    return File('${dir.path}/$_fileName');
  }

  Future<String> _readCache(File file) async {
    return file.readAsString();
  }

  Future<void> _writeCache(File file, String data) async {
    await file.writeAsString(data, flush: true);
  }

  Future<String> _fetchFromBackend() async {
    final uri = Uri.parse('${BackendConfig.baseUrl}/api/predictions/tips');

    final response = await http.get(uri);

    if (response.statusCode != 200) {
      throw Exception('HTTP ${response.statusCode}');
    }

    return response.body;
  }

  Future<String> _getCachedPredictions({
    Duration maxAge = const Duration(hours: 24),
  }) async {
    final file = await _getCacheFile();
    final exists = await file.exists();

    String? cachedData;
    DateTime? lastModified;

    if (exists) {
      lastModified = await file.lastModified();
      cachedData = await _readCache(file);

      final isFresh = DateTime.now().difference(lastModified) <= maxAge;

      if (isFresh) {
        return cachedData;
      }
    }

    try {
      final data = await _fetchFromBackend();
      await _writeCache(file, data);
      return data;
    } catch (e) {
      // backend failed (down / not found / connection error)

      // if any cached data available, return it even if expired
      if (cachedData != null) {
        return cachedData;
      }

      rethrow;
    }
  }

  Future<List<ZoneTipData>> getTipPredictions() async {
    final rawJson = await _getCachedPredictions();

    final decoded = jsonDecode(rawJson);

    if (decoded is! Map) {
      throw Exception('Expected Map but got ${decoded.runtimeType}');
    }

    final zones =
        (decoded['zones'] as List)
            .map((z) => ZoneTipData.fromJson(z as Map<String, dynamic>))
            .toList()
          ..sort((a, b) => b.expectedTipUsd.compareTo(a.expectedTipUsd));

    return zones;
  }
}

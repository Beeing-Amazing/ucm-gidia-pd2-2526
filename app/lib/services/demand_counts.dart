import 'dart:convert';
import 'dart:io';
import 'dart:ui';

import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import '../services/backend_config.dart';


const heatmapLow  = Color(0x7700C8FF);
const heatmapMid  = Color(0xAA00E676);
const heatmapHigh = Color(0xDDF5C518);

class DemandCountsService {
  static final DemandCountsService _instance =
      DemandCountsService._internal();

  factory DemandCountsService() => _instance;
  DemandCountsService._internal();

  String _cacheFileName(bool isFhvhv) =>
      isFhvhv ? 'zone_demand_forecast_fhv.json' : 'zone_demand_forecast_taxi.json';

  Future<File> _getCacheFile(bool isFhvhv) async {
    final dir = await getApplicationDocumentsDirectory();
    return File('${dir.path}/${_cacheFileName(isFhvhv)}');
  }

  Future<String> _readCache(File file) async {
    return file.readAsString();
  }

  Future<void> _writeCache(File file, String data) async {
    await file.writeAsString(data, flush: true);
  }

  Future<String> _fetchFromBackend(bool isFhvhv) async {
    final uri = Uri.parse(
      '${BackendConfig.baseUrl}/api/predictions/demand?is_fhvhv=$isFhvhv');

    final response = await http.get(uri);

    if (response.statusCode != 200) {
      throw Exception('HTTP ${response.statusCode}');
    }

    return response.body;
  }

  Future<Map<String, double>> getDemandMap({
    int? hour,
    bool isFhvhv = false,
    Duration maxAge = const Duration(hours: 12),
  }) async {
    final file = await _getCacheFile(isFhvhv);
    final exists = await file.exists();

    String? cachedData;
    DateTime? lastModified;

    if (exists) {
      lastModified = await file.lastModified();
      cachedData = await _readCache(file);

      final isFresh =
          DateTime.now().difference(lastModified) <= maxAge;

      if (isFresh) {
        return _parseForecast(cachedData, hour: hour);
      }
    }

    try {
      final data = await _fetchFromBackend(isFhvhv);
      await _writeCache(file, data);
      return _parseForecast(data, hour: hour);
    } catch (e) {
      if (cachedData != null) {
        return _parseForecast(cachedData, hour: hour);
      }
      rethrow;
    }
  }

  Map<String, double> _parseForecast(
    String jsonStr, {
    int? hour,
  }) {
    final decoded = json.decode(jsonStr);
    final List forecast = decoded['forecast'];

    if (forecast.isEmpty) return {};

    Map selected;

    if (hour != null) {
      selected = forecast.firstWhere(
        (f) => f['hour'] == hour,
        orElse: () => forecast.first,
      );
    } else {
      selected = forecast.first; // default: first hour
    }

    final zones = selected['zones'] as List;

    final Map<String, double> result = {};

    for (final z in zones) {
      final id = z['zone_id'].toString();
      final intensity = (z['intensity'] as num).toDouble();
      result[id] = intensity;
    }

    return result;
  }

  /// color gradient — zonas con 0 demanda son invisibles
  Color intensityToColor(double value) {
    if (value == 0) return const Color(0x00000000);

    final clamped = value.clamp(0.0, 1.0);
    const mid = 0.35;

    const low  = heatmapLow;
    const half = heatmapMid;
    const high = heatmapHigh;

    if (clamped < mid) {
      return Color.lerp(low, half, clamped / mid)!;
    } else {
      return Color.lerp(half, high, (clamped - mid) / (1 - mid))!;
    }
  }
}

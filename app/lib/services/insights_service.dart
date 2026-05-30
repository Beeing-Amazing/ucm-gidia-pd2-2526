import 'dart:io';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import '../constants.dart';

class ZoneStat {
  final int locationId;
  final String zoneName, borough;
  final double avgDailyPickups;

  const ZoneStat({
    required this.locationId,
    required this.zoneName,
    required this.borough,
    required this.avgDailyPickups,
  });

  factory ZoneStat.fromJson(Map<String, dynamic> j) => ZoneStat(
    locationId: j['PULocationID'] as int,
    zoneName: j['pickup_zone'] as String,
    borough: j['pickup_borough'] as String,
    avgDailyPickups: (j['avg_daily_pickups'] as num).toDouble(),
  );
}

class InsightsOverview {
  final int totalTrips;
  final double avgFare, avgTipPct, avgTripMiles, avgTripTimeMin;
  final List<ZoneStat> topZones;

  const InsightsOverview({
    required this.totalTrips,
    required this.avgFare,
    required this.avgTipPct,
    required this.avgTripMiles,
    required this.avgTripTimeMin,
    required this.topZones,
  });

  factory InsightsOverview.fromJson(Map<String, dynamic> j) => InsightsOverview(
    totalTrips: j['total_trips'] as int,
    avgFare: (j['avg_fare'] as num).toDouble(),
    avgTipPct: (j['avg_tip_pct'] as num).toDouble(),
    avgTripMiles: (j['avg_trip_miles'] as num).toDouble(),
    avgTripTimeMin: (j['avg_trip_time_min'] as num).toDouble(),
    topZones: (j['top_zones'] as List).map((z) => ZoneStat.fromJson(z as Map<String, dynamic>)).toList(),
  );
}

class ZoneForecast {
  final int zoneId, predictedPickups;
  final String zoneName, borough;
  final double intensity;

  const ZoneForecast({
    required this.zoneId,
    required this.predictedPickups,
    required this.zoneName,
    required this.borough,
    required this.intensity,
  });
}

class ForecastHour {
  final int hour, totalPickups;
  final List<ZoneForecast> zones;

  const ForecastHour({
    required this.hour,
    required this.totalPickups,
    required this.zones,
  });
}

class InsightsService {
  static final InsightsService _instance = InsightsService._internal();
  factory InsightsService() => _instance;
  InsightsService._internal();


  Future<InsightsOverview> getOverview({
    bool isFhvhv = false,
    Duration maxAge = const Duration(minutes: 30),
  }) async {
    final file = await _getCacheFile(
      'insights_overview_${isFhvhv ? "fhvhv" : "yellow"}.json',
    );

    String? cached;
    DateTime? lastModified;

    if (await file.exists()) {
      cached = await _readCache(file);
      lastModified = await file.lastModified();

      final isFresh =
          DateTime.now().difference(lastModified) <= maxAge;

      if (isFresh) {
        return InsightsOverview.fromJson(
          json.decode(cached) as Map<String, dynamic>,
        );
      }
    }

    try {
      final response = await http.get(
        Uri.parse('$BACKEND_URL/api/insights/overview?is_fhvhv=$isFhvhv'),
      );

      if (response.statusCode != 200) {
        throw Exception('HTTP ${response.statusCode}');
      }

      await _writeCache(file, response.body);

      return InsightsOverview.fromJson(
        json.decode(response.body) as Map<String, dynamic>,
      );
    } catch (e) {
      if (cached != null) {
        return InsightsOverview.fromJson(
          json.decode(cached) as Map<String, dynamic>,
        );
      }
      rethrow;
    }
  }


  Future<List<ForecastHour>> getForecast({
    bool isFhvhv = false,
    Duration maxAge = const Duration(minutes: 15),
  }) async {
    final file = await _getCacheFile(
      'insights_forecast_${isFhvhv ? "fhvhv" : "yellow"}.json',
    );

    String? cached;
    DateTime? lastModified;

    if (await file.exists()) {
      cached = await _readCache(file);
      lastModified = await file.lastModified();

      final isFresh =
          DateTime.now().difference(lastModified) <= maxAge;

      if (isFresh) {
        return _parseForecast(json.decode(cached));
      }
    }

    try {
      final response = await http.get(
        Uri.parse('$BACKEND_URL/api/predictions/demand?is_fhvhv=$isFhvhv'),
      );

      if (response.statusCode != 200) {
        throw Exception('HTTP ${response.statusCode}');
      }

      await _writeCache(file, response.body);

      return _parseForecast(json.decode(response.body));
    } catch (e) {
      if (cached != null) {
        return _parseForecast(json.decode(cached));
      }
      rethrow;
    }
  }


  List<ForecastHour> _parseForecast(Map<String, dynamic> data) {
    return (data['forecast'] as List).map((h) {
      final zones = (h['zones'] as List).map((z) => ZoneForecast(
        zoneId: z['zone_id'] as int,
        zoneName: z['zone_name'] as String,
        borough: z['borough'] as String,
        predictedPickups: (z['predicted_pickups'] as num).toInt(),
        intensity: (z['intensity'] as num).toDouble(),
      )).toList()
        ..sort((a, b) => b.predictedPickups.compareTo(a.predictedPickups));

      return ForecastHour(
        hour: h['hour'] as int,
        totalPickups: zones.fold(0, (s, z) => s + z.predictedPickups),
        zones: zones,
      );
    }).toList();
  }


  Future<File> _getCacheFile(String name) async {
    final dir = await getApplicationDocumentsDirectory();
    return File('${dir.path}/$name');
  }

  Future<String> _readCache(File file) async {
    return file.readAsString();
  }

  Future<void> _writeCache(File file, String data) async {
    await file.writeAsString(data, flush: true);
  }
}

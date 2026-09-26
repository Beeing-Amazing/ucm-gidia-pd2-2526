import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import '../services/backend_config.dart';


class TrafficCamera {
  final String id;
  final String road;
  final String direction;
  final double lat;
  final double lng;
  final String streamUrl;
  final String snapshotId;

  const TrafficCamera({
    required this.id,
    required this.road,
    required this.direction,
    required this.lat,
    required this.lng,
    required this.streamUrl,
    required this.snapshotId,
  });

  factory TrafficCamera.fromJson(Map<String, dynamic> j) => TrafficCamera(
        id:         j['ID'].toString(),
        road:       j['RoadwayName'] ?? '',
        direction:  j['DirectionOfTravel'] ?? '',
        lat:        (j['Latitude'] as num).toDouble(),
        lng:        (j['Longitude'] as num).toDouble(),
        streamUrl:  j['VideoUrl'] ?? '',
        snapshotId: j['id_url_cam'].toString(),
      );
}

class CamerasService {
  static final CamerasService _instance = 
    CamerasService._internal();
  factory CamerasService() => _instance;
  CamerasService._internal();

  static const _fileName = 'NYC_Traffic_Cameras.json';

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
    final uri = Uri.parse(
      '${BackendConfig.baseUrl}/api/data/nyc_traffic_cameras');

    final response = await http.get(uri);

    if (response.statusCode != 200) {
      throw Exception('HTTP ${response.statusCode}');
    }

    return response.body;
  }

  Future<String> _getCachedCameras({
    Duration maxAge = const Duration(hours: 24),
  }) async {
    final file = await _getCacheFile();
    final exists = await file.exists();

    String? cachedData;
    DateTime? lastModified;

    if (exists) {
      lastModified = await file.lastModified();
      cachedData = await _readCache(file);

      final isFresh =
          DateTime.now().difference(lastModified) <= maxAge;

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

  Future<List<TrafficCamera>> getCameras() async {
    final rawJson = await _getCachedCameras();

    final decoded = jsonDecode(rawJson);

    if (decoded is! Map) {
      throw Exception('Expected Map but got ${decoded.runtimeType}');
    }

    return decoded.values
        .expand((list) => list as List)
        .map((json) => TrafficCamera.fromJson(json))
        .where((cam) =>
            cam.road.isNotEmpty &&
            cam.streamUrl.isNotEmpty)
        .toList();
  }
}

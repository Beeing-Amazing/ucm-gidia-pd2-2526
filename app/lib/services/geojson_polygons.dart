import 'dart:io';
import 'dart:ui' show Color;
import 'package:path_provider/path_provider.dart';
import 'package:geojson_vi/geojson_vi.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:http/http.dart' as http;
import '../constants.dart';

// FastAPI server
final String _baseUrl = BACKEND_URL;

class GeoJsonPolygonsService {
  static final GeoJsonPolygonsService _instance =
    GeoJsonPolygonsService._internal();
  factory GeoJsonPolygonsService() => _instance;
  GeoJsonPolygonsService._internal();

  static const _fileName = 'NYC_Taxi_Zones.json';

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
    final uri = Uri.parse('$_baseUrl/api/data/taxi_zone_lookup');

    final response = await http.get(uri);

    if (response.statusCode != 200) {
      throw Exception('HTTP ${response.statusCode}');
    }

    return response.body;
  }

  Future<String> _getGeoJson({
    Duration maxAge = const Duration(days: 30)
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

  Future<String> getRawGeoJson() async {
    return _getGeoJson();
  }

  // Future<List<Polygon>> getZonePolygons({
  //   Color fillColor = const Color(0x55377EF6), 
  //   Color borderColor = const Color(0x90ffffff),
  //   double borderStrokeWidth = 1.6,
  // }) async {
  //   final geoJsonStr = await _getGeoJson();

  //   return parseGeoJsonToPolygons(
  //     geoJsonStr,
  //     fillColor: fillColor,
  //     borderColor: borderColor,
  //     borderStrokeWidth: borderStrokeWidth,
  //   );
  // }
}


List<Polygon> parseGeoJsonToPolygons(
  String geojsonStr, {
  required Map<String, double> demandMap,
  required Color Function(double) colorMapper,
  Color borderColor = const Color(0x55377EF6),
  double borderStrokeWidth = 1,
}) {
  final collection = GeoJSONFeatureCollection.fromJSON(geojsonStr);

  final polygons = <Polygon>[];

  for (final feature in collection.features) {
    final geom = feature?.geometry;
    if (geom == null) continue;

    final props = feature?.properties;

    final zoneId = props?['id']?.toString();
    final intensity = demandMap[zoneId] ?? 0.0;

    final fillColor = colorMapper(intensity);
    // zonas sin demanda: ocultar también el borde para que sean invisibles
    final effectiveBorder = fillColor.a == 0 ? const Color(0x00000000) : borderColor;

    if (geom is GeoJSONPolygon) {
      polygons.add(
        _buildPolygon(
          geom.coordinates,
          fillColor,
          effectiveBorder,
          borderStrokeWidth,
        ),
      );
    }

    if (geom is GeoJSONMultiPolygon) {
      for (final coords in geom.coordinates) {
        polygons.add(
          _buildPolygon(
            coords,
            fillColor,
            effectiveBorder,
            borderStrokeWidth,
          ),
        );
      }
    }
  }

  return polygons;
}


List<LatLng> _cleanRing(List<LatLng> points) {
  if (points.length > 1 && points.first == points.last) {
    return points.sublist(0, points.length - 1);
  }
  return points;
}


Polygon _buildPolygon(
  List<List<List<double>>> rings,
  Color fillColor,
  Color borderColor,
  double borderStrokeWidth,
) {
  if (rings.isEmpty) return Polygon(points: []);

  var exterior = rings.first
      .where((xy) => xy.length >= 2)
      .map((xy) => LatLng(xy[1], xy[0]))
      .toList();

  exterior = _cleanRing(exterior);
  if (exterior.length < 4) return Polygon(points: []);

  return Polygon(
    points: exterior,
    color: fillColor,
    isFilled: true,
    borderColor: borderColor,
    borderStrokeWidth: borderStrokeWidth,
  );
}

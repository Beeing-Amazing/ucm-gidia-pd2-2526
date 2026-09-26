import 'package:flutter/material.dart';
import '../app_theme.dart';
import 'package:latlong2/latlong.dart';

import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_map_marker_cluster/flutter_map_marker_cluster.dart';

import 'cameras.dart';
import '../services/geojson_polygons.dart';
import '../services/backend_cameras.dart';
import '../services/demand_counts.dart';
import '../services/backend_config.dart';


class MapOverviewMainScreen extends StatefulWidget {
  final Function(TrafficCamera) onCameraSelected;

  const MapOverviewMainScreen({
    super.key,
    required this.onCameraSelected,
  });

  @override
  State<MapOverviewMainScreen> createState() => _MapOverviewMainScreenState ();
}

class _MapOverviewMainScreenState extends State<MapOverviewMainScreen> {
  String? _geoJsonCache;
  List<Polygon> _polygons = [];
  List<TrafficCamera> _cameras = [];
  double _currentZoom = 12;
  TrafficCamera? _selectedCamera;
  String? _lastCameraImageUrl;
  double _overlayDragX = 0;

  int currentHour = 2;
  bool _isLoadingPolygons = false;
  bool _isFhvhv = true;

  @override
  void initState() {
    super.initState();
    _loadData();
    _checkBackend();
  }

  bool _backendOnline = true;
  Future<void> _checkBackend() async {
    final online = await BackendConfig.testServer();
    if (!mounted) return;
    setState(() { _backendOnline = online; }); 
  }

  Future<void> _loadData() async {
    setState(() => _isLoadingPolygons = true);

    final geoService = GeoJsonPolygonsService();
    final demandService = DemandCountsService();

    _geoJsonCache ??= await geoService.getRawGeoJson();
    final geoJsonStr = _geoJsonCache!;
    
    final demandMap =
        await demandService.getDemandMap(hour: currentHour, isFhvhv: _isFhvhv);
    final polygons = parseGeoJsonToPolygons(
      geoJsonStr,
      demandMap: demandMap,
      colorMapper: demandService.intensityToColor,
      borderColor: const Color(0x18ffffff),
      borderStrokeWidth: 0.8,
    );

    final cameras =
        await CamerasService().getCameras();


    if (!mounted) return;

    setState(() {
      _polygons = polygons;
      _cameras = cameras;
      _selectedCamera = null;
      _lastCameraImageUrl = null;
      _isLoadingPolygons = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Container(
          color: const Color(0xFF151515),
        ),
        FlutterMap(
          options: MapOptions(
            initialCenter: LatLng(40.712, -74.005),
            initialZoom: _currentZoom,

            minZoom: 10.8,
            maxZoom: 17,

            cameraConstraint: CameraConstraint.contain(
              bounds: LatLngBounds(
                LatLng(40.45, -74.35),
                LatLng(40.95, -73.65),
              ),
            ),

            interactionOptions: const InteractionOptions(
              flags:
                InteractiveFlag.drag |
                InteractiveFlag.pinchZoom |
                InteractiveFlag.doubleTapZoom |
                InteractiveFlag.flingAnimation |
                InteractiveFlag.rotate,
            ),

            onPositionChanged: (position, hasGesture) {
              final zoom = position.zoom;
              if (zoom != null) {
                setState(() {
                  _currentZoom = zoom;
                });
              }
            },
          ),

          children: [
            if (_backendOnline)
              TileLayer(
                urlTemplate: '${BackendConfig.baseUrl}/map/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.museekarapp.app',
              ),

            /// POLYGONS
            PolygonLayer(
              polygons: _polygons,
            ),

            /// CAMERA CLUSTER LAYER
            MarkerClusterLayerWidget(
              options: MarkerClusterLayerOptions(
                maxClusterRadius: 50,
                size: const Size(10, 10),
                alignment: Alignment.center,
                padding: const EdgeInsets.all(40),

                maxZoom: 17,

                markers: _currentZoom >= 11
                  ? _cameras.map((cam) {
                      return Marker(
                        point: LatLng(cam.lat, cam.lng),
                        width: 30,
                        height: 30,
                        child: Material(
                          color: Colors.transparent,
                          shape: const CircleBorder(),
                          clipBehavior: Clip.antiAlias,
                          child: InkResponse(
                            onTap: () {
                              _showCameraDetails(cam);
                            },
                            highlightShape: BoxShape.circle,
                            customBorder: const CircleBorder(),
                            splashColor: Colors.blue.withValues(alpha: 0.4),
                            highlightColor: Colors.blue.withValues(alpha: 0.4),
                            containedInkWell: false,
                            child: Stack(
                              alignment: Alignment.topCenter,
                              children: [
                                Positioned(
                                  top: 2,
                                  child: Container(
                                    width: 24,
                                    height: 24,
                                    decoration: BoxDecoration(
                                      color: const Color.fromARGB(255, 70, 70, 70),
                                      borderRadius: BorderRadius.circular(20),
                                    ),
                                    child: Align(
                                      alignment: Alignment.bottomCenter,
                                      child: Transform.translate(
                                        offset: const Offset(0, 2),
                                        child: Transform.rotate(
                                          angle: 0.785, // 45 degrees for soft teardrop tip
                                          child: Container(
                                            width: 16,
                                            height: 16,
                                            decoration: const BoxDecoration(
                                              color: Color.fromARGB(255, 70, 70, 70),
                                              borderRadius: BorderRadius.all(Radius.circular(4)),
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                  ),
                                ),

                                // Yellow circular center
                                Positioned(
                                  top: 5,
                                  child: Container(
                                    width: 18,
                                    height: 18,
                                    decoration: BoxDecoration(
                                      color: yellow,
                                      shape: BoxShape.circle,
                                      boxShadow: [
                                        BoxShadow(
                                          blurRadius: 3,
                                          color: Colors.black.withValues(alpha: 0.2),
                                        ),
                                      ],
                                    ),
                                    child: const Center(
                                      child: Icon(
                                        Icons.videocam_rounded,
                                        color: Color.fromARGB(255, 70, 70, 70),
                                        size: 14,
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      );
                    }).toList()
                  : [],

                builder: (context, markers) {

                  return Container(
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: yellow,
                      boxShadow: [
                        BoxShadow(
                          blurRadius: 2,
                          color: Colors.black.withValues(alpha: 0.15),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ]
        ),
        Positioned(
          top: MediaQuery.of(context).padding.top + 12,
          right: 16,
          child: _MapTypeToggle(
            isFhvhv: _isFhvhv,
            onChanged: (v) {
              setState(() => _isFhvhv = v);
              _loadData();
            },
          ),
        ),

        Positioned(
          left: 16,
          right: 16,
          bottom: 20 + MediaQuery.of(context).padding.bottom,
          child: _buildHourSlider(),
        ),

        /// optional loading indicator
        if (_isLoadingPolygons)
          const Positioned(
            top: 50,
            left: 0,
            right: 0,
            child: Center(child: CircularProgressIndicator(color: yellow)),
          ),

        if (_selectedCamera != null)
          _buildCameraOverlay(_selectedCamera!),
      ]
    );
  }

  Widget _buildHourSlider() {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 6),
      decoration: BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: divider),
        boxShadow: [
          BoxShadow(
            blurRadius: 12,
            color: Colors.black.withValues(alpha: 0.4),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'Hour',
                style: TextStyle(color: muted, fontSize: 11, fontWeight: FontWeight.w600),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                decoration: BoxDecoration(
                  color: yellow.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  '+${currentHour + 1}h',
                  style: const TextStyle(
                    color: yellow,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          /// Slider
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              trackHeight: 4,
              activeTrackColor: yellow,
              inactiveTrackColor: surface2,
              thumbColor: yellow,
              overlayColor: yellow.withValues(alpha: 0.2),
            thumbShape: const RoundSliderThumbShape(
              enabledThumbRadius: 8,
            ),
            overlayShape: const RoundSliderOverlayShape(
              overlayRadius: 14,
            ),
            ),
            child: Slider(
              value: currentHour.toDouble(),
              min: 0,
              max: 12,
              divisions: 12,
              label: '+${currentHour + 1}h',
              onChanged: (value) {
                setState(() {
                  currentHour = value.round();
              });
            },
            onChangeEnd: (value) async {
              await _loadData();
            },
            ),
          ),
          const SizedBox(height: 2),
          Row(
            children: [
              const Text('Low', style: TextStyle(color: muted, fontSize: 10)),
              const SizedBox(width: 6),
              Expanded(
                child: Container(
                  height: 5,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(3),
                    gradient: const LinearGradient(
                      colors: [heatmapLow, heatmapMid, heatmapHigh],
                      stops: [0.0, 0.35, 1.0],
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 6),
              const Text('High', style: TextStyle(color: muted, fontSize: 10)),
            ],
          ),
          const SizedBox(height: 4),
        ],
      ),
    );
  }

  void _showCameraDetails(TrafficCamera cam) {
    final timestamp = DateTime.now().millisecondsSinceEpoch ~/ 1000;

    setState(() {
      _selectedCamera = cam;
      _lastCameraImageUrl = 'https://511ny.org/map/Cctv/${cam.snapshotId}?t=$timestamp';
    });
  }

  Widget _buildCameraOverlay(TrafficCamera cam) {
    final screenWidth = MediaQuery.of(context).size.width;
    double opacity =
      1 - (_overlayDragX.abs() / screenWidth).clamp(0.0, 1.0);

    return AnimatedPositioned(
      duration: const Duration(milliseconds: 200),
      curve: Curves.easeOut,
      top: MediaQuery.of(context).padding.top + 12 + 32 + 8,
      left: _overlayDragX,
      right: -_overlayDragX,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onHorizontalDragUpdate: (details) {
          setState(() {
            _overlayDragX += details.delta.dx;
          });
        },
        onHorizontalDragEnd: (details) {
          final velocity = details.primaryVelocity ?? 0;

          // dismiss if far enough OR fast swipe
          if (_overlayDragX.abs() > screenWidth * 0.25 ||
              velocity.abs() > 800) {
            setState(() {
              _selectedCamera = null;
              _overlayDragX = 0;
            });
          } else {
            // snap back
            setState(() {
              _overlayDragX = 0;
            });
          }
        },
        child: Opacity(
          opacity: opacity,
          child: _overlayContent(cam),
        ),
      ),
    );
  }

  Widget _overlayContent(TrafficCamera cam) {
    return Material(
      color: Colors.transparent,
      child: Container(
        margin: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: card,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: divider),
        ),
        child: Stack(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.network(
                  _lastCameraImageUrl!,
                  fit: BoxFit.cover,
                  width: double.infinity,
                  height: 220,
                  headers: const {
                    'User-Agent':
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                    'Referer': 'https://511ny.org/',
                  },
                  loadingBuilder: (context, child, progress) {
                    if (progress == null) return child;
                    return const SizedBox(
                      height: 220,
                      child: Center(child: CircularProgressIndicator()),
                    );
                  },
                  errorBuilder: (context, error, stackTrace) {
                    return const SizedBox(
                      height: 220,
                      child: Center(child: Text('Image unavailable')),
                    );
                  },
                ),
              ),

              Positioned(
                top: 8,
                right: 8,
                child: GestureDetector(
                  onTap: () {
                    setState(() => _selectedCamera = null);
                  },
                  child: Container(
                    decoration: BoxDecoration(
                      color: Colors.black54,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    padding: const EdgeInsets.all(6),
                    child: const Icon(Icons.close, color: Colors.white),
                  ),
                ),
              ),

              if (cam.streamUrl.isNotEmpty)
                Positioned(
                  bottom: 8,
                  left: 8,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: yellow,
                      foregroundColor: Colors.black,
                    ),
                    onPressed: () {
                      setState(() => _selectedCamera = null);
                      widget.onCameraSelected(cam);
                    },
                    child: const Text("View live camera"),
                  ),
                ),
            ],
          ),
      ),
    );
  }
}

class _MapTypeToggle extends StatelessWidget {
  final bool isFhvhv;
  final ValueChanged<bool> onChanged;

  const _MapTypeToggle({required this.isFhvhv, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 30,
      decoration: BoxDecoration(
        color: surface2,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: divider),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _chip('FHV', isFhvhv, () => onChanged(true)),
          _chip('Taxi', !isFhvhv, () => onChanged(false)),
        ],
      ),
    );
  }

  Widget _chip(String label, bool active, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: active ? yellow : Colors.transparent,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: active ? Colors.black : muted,
            fontWeight: FontWeight.w700,
            fontSize: 11,
          ),
        ),
      ),
    );
  }
}
import 'package:flutter/material.dart';
import '../app_theme.dart';
import 'package:video_player/video_player.dart';
import '../services/backend_cameras.dart';

class CamerasMainScreen extends StatefulWidget {
  final TrafficCamera? initialCamera;

  const CamerasMainScreen({super.key, this.initialCamera});
  // const CamerasMainScreen({super.key});

  @override
  State<CamerasMainScreen> createState() => _CamerasMainScreenState();
}

class _CamerasMainScreenState extends State<CamerasMainScreen> {
  List<TrafficCamera> _cameras = [];
  TrafficCamera? _selectedCamera;

  VideoPlayerController? _videoController;

  bool _videoLoading = false;
  bool _videoError = false;

  final TextEditingController _searchController = TextEditingController();
  String _searchQuery = '';

  @override
  void initState() {
    super.initState();
    _searchController.addListener(() {
      setState(() {
        _searchQuery = _searchController.text;
      });
    });
    _loadCameras();
  }

  @override
  void didUpdateWidget(covariant CamerasMainScreen oldWidget) {
    super.didUpdateWidget(oldWidget);

    if (widget.initialCamera != null &&
        widget.initialCamera?.id != oldWidget.initialCamera?.id) {
      _initVideo(widget.initialCamera!);
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    _videoController?.dispose();
    super.dispose();
  }

  Future<void> _loadCameras() async {
    try {
      final cameras = await CamerasService().getCameras();

      if (!mounted) return;

      setState(() {
        _cameras = cameras;
      });

      if (cameras.isNotEmpty) {
        final camToLoad = widget.initialCamera != null
          ? cameras.firstWhere(
              (c) => c.id == widget.initialCamera!.id,
              orElse: () => cameras.first,
            )
          : cameras.first;
        _initVideo(camToLoad);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _cameras = [];
      });
    }
  }

  Future<void> _initVideo(TrafficCamera cam) async {
    final oldController = _videoController;
    _videoController = null;
    await oldController?.dispose();

    if (!mounted) return;

    setState(() {
      _selectedCamera = cam;
      _videoLoading = true;
      _videoError = false;
    });

    final controller =
        VideoPlayerController.networkUrl(Uri.parse(cam.streamUrl));

    _videoController = controller;

    try {
      await controller.initialize().timeout(const Duration(seconds: 12));

      if (!mounted || _selectedCamera?.id != cam.id) return;

      await controller.setLooping(true);
      await controller.play();

      if (!mounted) return;

      setState(() {
        _videoLoading = false;
        _videoError = false;
      });
    } catch (_) {
      if (!mounted || _selectedCamera?.id != cam.id) return;

      setState(() {
        _videoLoading = false;
        _videoError = true;
      });
    }
  }

  Map<String, List<TrafficCamera>> _groupCameras() {
    final query = _searchQuery.toLowerCase().trim();
    final filtered = query.isEmpty
        ? _cameras
        : _cameras.where((c) =>
            c.road.toLowerCase().contains(query) ||
            c.direction.toLowerCase().contains(query)).toList();

    final groups = <String, List<TrafficCamera>>{};
    for (final cam in filtered) {
      groups.putIfAbsent(cam.road, () => []).add(cam);
    }
    return Map.fromEntries(groups.entries.toList()..sort((a, b) => a.key.compareTo(b.key)));
  }

  @override
  Widget build(BuildContext context) {
    if (_cameras.isEmpty) {
      return const Scaffold(
        backgroundColor: bg,
        body: Center(child: CircularProgressIndicator(color: yellow)),
      );
    }

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        backgroundColor: bg,
        elevation: 0,
        titleSpacing: 20,
        scrolledUnderElevation: 0,
        title: const Text(
          'Dynamic Viewer',
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 22,
            letterSpacing: -0.8,
          ),
        ),
      ),
      body: Builder(builder: (context) {
        final grouped = _groupCameras();
        return Column(
          children: [
            if (_selectedCamera != null) _buildVideoPlayer(),
            _buildSearchBar(),
            _buildCountRow(grouped),
            Expanded(child: _buildGroupedList(grouped)),
          ],
        );
      }),
    );
  }

  // --- VIDEO ---

  Widget _buildVideoPlayer() {
    return Container(
      height: 275,
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      decoration: BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: divider),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        fit: StackFit.expand,
        children: [
          _buildVideoContent(),
          if (_videoController != null &&
              _videoController!.value.isInitialized &&
              !_videoLoading)
            _buildLiveBadge(),
          if (_selectedCamera != null) _buildCameraLabel(),
        ],
      ),
    );
  }

  Widget _buildVideoContent() {
    final controller = _videoController;

    if (_videoError) {
      return _buildErrorState();
    }

    if (_videoLoading ||
        controller == null ||
        !controller.value.isInitialized) {
      return const Center(
        child: CircularProgressIndicator(color: yellow),
      );
    }

    return FittedBox(
      fit: BoxFit.cover,
      child: SizedBox(
        width: controller.value.size.width,
        height: controller.value.size.height,
        child: VideoPlayer(controller),
      ),
    );
  }

  Widget _buildErrorState() {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.videocam_off, size: 40, color: muted),
        const SizedBox(height: 8),
        const Text(
          'Stream not available',
          style: TextStyle(color: muted, fontSize: 13),
        ),
        if (_selectedCamera != null)
          Text(
            _selectedCamera!.road,
            style: const TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w600,
            ),
          ),
      ],
    );
  }

  Widget _buildLiveBadge() {
    return const Positioned(
      top: 10,
      left: 10,
      child: _Badge(),
    );
  }

  Widget _buildCameraLabel() {
    return Positioned(
      bottom: 10,
      left: 10,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: Colors.black.withValues(alpha: 0.6),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _selectedCamera!.road,
              style: const TextStyle(color: muted, fontSize: 10),
            ),
            Text(
              _selectedCamera!.direction,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // --- SEARCH ---

  Widget _buildSearchBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
      child: TextField(
        controller: _searchController,
        style: const TextStyle(color: Colors.white, fontSize: 14),
        decoration: InputDecoration(
          hintText: 'Search by road or direction...',
          hintStyle: const TextStyle(color: muted, fontSize: 14),
          prefixIcon: const Icon(Icons.search, color: muted, size: 20),
          suffixIcon: _searchQuery.isNotEmpty
              ? IconButton(
                  icon: const Icon(Icons.clear, color: muted, size: 18),
                  onPressed: () => _searchController.clear(),
                )
              : null,
          isDense: true,
          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          filled: true,
          fillColor: card,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: divider),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: divider),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: yellow),
          ),
        ),
      ),
    );
  }

  Widget _buildCountRow(Map<String, List<TrafficCamera>> grouped) {
    final total = grouped.values.fold(0, (sum, list) => sum + list.length);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Row(
        children: [
          const Text(
            'Available Cameras',
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w700,
              fontSize: 14,
              letterSpacing: -0.3,
            ),
          ),
          const Spacer(),
          Text(
            '$total feeds · ${grouped.length} roads',
            style: const TextStyle(color: muted, fontSize: 11),
          ),
        ],
      ),
    );
  }

  // --- GROUPED LIST ---

  Widget _buildGroupedList(Map<String, List<TrafficCamera>> grouped) {
    if (grouped.isEmpty) {
      return const Center(
        child: Text('No cameras match your search.', style: TextStyle(color: muted)),
      );
    }

    final roads = grouped.keys.toList();

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      itemCount: roads.length,
      itemBuilder: (ctx, i) {
        final road = roads[i];
        final cams = grouped[road]!;
        return _buildRoadSection(road, cams);
      },
    );
  }

  Widget _buildRoadSection(String road, List<TrafficCamera> cams) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 14, bottom: 6),
          child: Text(
            road.toUpperCase(),
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: muted,
              letterSpacing: 0.6,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        ...cams.map(_buildItem),
      ],
    );
  }

  Widget _buildItem(TrafficCamera cam) {
    final isSelected = _selectedCamera?.id == cam.id;

    return GestureDetector(
      onTap: () => _initVideo(cam),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: isSelected ? yellow.withValues(alpha: 0.12) : card,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected ? yellow.withValues(alpha: 0.5) : divider,
          ),
        ),
        child: Row(
          children: [
            Icon(
              Icons.videocam,
              color: isSelected ? yellow : muted,
              size: 20,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Row(
                children: [
                  Text(
                    cam.direction.isNotEmpty ? cam.direction : 'Camera ${cam.id}',
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                      color: isSelected ? yellow : Colors.white,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    '#${cam.id}',
                    style: TextStyle(
                      fontSize: 11,
                      color: isSelected ? yellow.withValues(alpha: 0.6) : muted,
                    ),
                  ),
                ],
              ),
            ),
            if (isSelected) _buildStatus(),
          ],
        ),
      ),
    );
  }

  Widget _buildStatus() {
    if (_videoLoading) {
      return const SizedBox(
        width: 16,
        height: 16,
        child: CircularProgressIndicator(strokeWidth: 2, color: yellow),
      );
    }
    if (_videoError) {
      return const Icon(Icons.wifi_off, size: 18, color: muted);
    }
    return const Icon(Icons.play_circle, color: yellow);
  }
}

// --- VIDEO DECORATOR ---

class _Badge extends StatelessWidget {
  const _Badge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: const Color.fromARGB(197, 244, 67, 54),
        borderRadius: BorderRadius.circular(4),
      ),
      child: const Text(
        '● LIVE',
        style: TextStyle(
          color: Colors.white,
          fontSize: 10,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

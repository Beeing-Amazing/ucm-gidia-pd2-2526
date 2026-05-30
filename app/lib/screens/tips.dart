import 'package:flutter/material.dart';
import '../app_theme.dart';
import '../services/tip_predictions_service.dart';


class Tips extends StatefulWidget {
  const Tips({super.key});
  @override
  State<Tips> createState() => _TipsState();
}

class _TipsState extends State<Tips> {
  List<ZoneTipData> _all = [];
  List<ZoneTipData> _filtered = [];
  String _query = '';
  bool _loading = true;
  String? _error;

  final _searchCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _searchCtrl.addListener(() {
      _query = _searchCtrl.text;
      _applyFilter();
    });
    _load();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final zones = await TipPredictionsService().getTipPredictions();
      if (!mounted) return;
      setState(() {
        _all = zones;
        _loading = false;
      });
      _applyFilter();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  void _applyFilter() {
    final q = _query.toLowerCase().trim();
    setState(() {
      _filtered = q.isEmpty
          ? List.of(_all)
          : _all
                .where(
                  (z) =>
                      z.zoneName.toLowerCase().contains(q) ||
                      z.borough.toLowerCase().contains(q),
                )
                .toList();
    });
  }

  int _stars(double usd) {
    if (usd >= 2.67) return 5;
    if (usd >= 1.84) return 4;
    if (usd >= 0.68) return 3;
    if (usd >= 0.25) return 2;
    return 1;
  }

  Color _tipColor(double usd) {
    if (usd >= 2.67) return const Color(0xFF4CD964);
    if (usd >= 1.84) return const Color(0xFF7DC855);
    if (usd >= 0.68) return const Color(0xFFF5C518);
    if (usd >= 0.25) return const Color(0xFFFF9500);
    return muted;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        backgroundColor: bg,
        elevation: 0,
        titleSpacing: 20,
        scrolledUnderElevation: 0,
        title: const Text(
          'Tips',
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 22,
            letterSpacing: -0.8,
          ),
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: yellow))
          : _error != null
          ? _buildErrorState()
          : Column(
              children: [
                _buildSearchBar(),
                _buildCountRow(),
                Expanded(child: _buildGrid()),
              ],
            ),
    );
  }

  Widget _buildSearchBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
      child: TextField(
        controller: _searchCtrl,
        style: const TextStyle(color: Colors.white, fontSize: 14),
        decoration: InputDecoration(
          hintText: 'Search by zone or borough...',
          hintStyle: const TextStyle(color: muted, fontSize: 14),
          prefixIcon: const Icon(Icons.search, color: muted, size: 20),
          suffixIcon: _query.isNotEmpty
              ? IconButton(
                  icon: const Icon(Icons.clear, color: muted, size: 18),
                  onPressed: () => _searchCtrl.clear(),
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

  Widget _buildCountRow() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Row(
        children: [
          const Text(
            'Tip Zones',
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w700,
              fontSize: 14,
              letterSpacing: -0.3,
            ),
          ),
          const Spacer(),
          Text(
            '${_filtered.length} zones · best tips first',
            style: const TextStyle(color: muted, fontSize: 11),
          ),
        ],
      ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.wifi_off_rounded, color: muted, size: 40),
          const SizedBox(height: 12),
          const Text(
            'Could not load predictions',
            style: TextStyle(color: muted),
          ),
          const SizedBox(height: 16),
          OutlinedButton(
            onPressed: _load,
            style: OutlinedButton.styleFrom(
              foregroundColor: yellow,
              side: const BorderSide(color: yellow),
            ),
            child: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildGrid() {
    if (_filtered.isEmpty) {
      return Center(
        child: Text(
          _query.isEmpty ? 'No zones loaded.' : 'No zones match your search.',
          style: const TextStyle(color: muted),
        ),
      );
    }
    return GridView.builder(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        crossAxisSpacing: 10,
        mainAxisSpacing: 10,
        childAspectRatio: 1.05,
      ),
      itemCount: _filtered.length,
      itemBuilder: (_, i) => _buildCard(_filtered[i]),
    );
  }

  Widget _buildCard(ZoneTipData zone) {
    final color = _tipColor(zone.expectedTipUsd);
    final stars = _stars(zone.expectedTipUsd);

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            zone.zoneName,
            style: const TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w600,
              fontSize: 13,
              height: 1.25,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: 4),
          Text(
            zone.borough,
            style: const TextStyle(fontSize: 11, color: muted),
          ),
          const Spacer(),
          Text(
            '\$${zone.expectedTipUsd.toStringAsFixed(2)}',
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: color,
              height: 1,
            ),
          ),
          const SizedBox(height: 4),
          Row(
            children: List.generate(
              5,
              (i) => Icon(
                i < stars ? Icons.star_rounded : Icons.star_outline_rounded,
                size: 14,
                color: i < stars ? color : divider,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

import 'dart:math';
import 'package:flutter/material.dart';
import '../app_theme.dart';
import '../services/insights_service.dart';


class Insights extends StatefulWidget {
  const Insights({super.key});
  @override
  State<Insights> createState() => _InsightsState();
}

class _InsightsState extends State<Insights> with SingleTickerProviderStateMixin {
  late final TabController _tabs;
  InsightsOverview? _overview;
  List<ForecastHour>? _forecast;
  bool _loading = true;
  int _selectedHour = 0;
  bool _isFhvhv = true;
  final _searchCtrl = TextEditingController();
  String _searchQuery = '';

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: 2, vsync: this);
    _searchCtrl.addListener(() => setState(() => _searchQuery = _searchCtrl.text));
    _load();
  }

  @override
  void dispose() {
    _tabs.dispose();
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    _searchCtrl.clear();
    setState(() { _loading = true; _searchQuery = ''; });
    final svc = InsightsService();
    final overview = await svc.getOverview(isFhvhv: _isFhvhv);
    final forecast = await svc.getForecast(isFhvhv: _isFhvhv);
    if (!mounted) return;
    setState(() {
      _overview = overview;
      _forecast = forecast;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        backgroundColor: bg,
        elevation: 0,
        titleSpacing: 20,
        title: const Text(
          'Insights',
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 22,
            letterSpacing: -0.8,
          ),
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: _TypeToggle(
              isFhvhv: _isFhvhv,
              onChanged: (v) {
                setState(() => _isFhvhv = v);
                _load();
              },
            ),
          ),
        ],
        bottom: TabBar(
          controller: _tabs,
          indicatorColor: yellow,
          indicatorWeight: 2,
          labelColor: yellow,
          unselectedLabelColor: muted,
          dividerColor: divider,
          labelStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
          tabs: const [Tab(text: 'Forecast'), Tab(text: 'Historical')],
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: yellow))
          : TabBarView(
              controller: _tabs,
              children: [_buildForecast(), _buildHistorical()],
            ),
    );
  }

  // Historical

  Widget _buildHistorical() {
    final o = _overview!;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
      children: [
        _buildKpiGrid(o),
        const SizedBox(height: 20),
        _sectionHeader('Top Zones by Volume'),
        const SizedBox(height: 8),
        ...o.topZones.asMap().entries.map(
          (e) => _buildHistZoneRow(e.key + 1, e.value, o.topZones.first.avgDailyPickups),
        ),
      ],
    );
  }

  Widget _buildKpiGrid(InsightsOverview o) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _kpiCard(
                _isFhvhv ? 'FHVHV Trips' : 'Yellow Trips',
                _fmt(o.totalTrips),
                _isFhvhv ? Icons.directions_car_rounded : Icons.local_taxi_rounded,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _kpiCard('Avg Fare', '\$${o.avgFare.toStringAsFixed(2)}', Icons.attach_money_rounded),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: _isFhvhv
                  ? _kpiCard('Avg Trip Time', '${o.avgTripTimeMin.toStringAsFixed(0)} min', Icons.timer_rounded)
                  : _kpiCard('Avg Tip %', '${o.avgTipPct.toStringAsFixed(1)}%', Icons.star_rounded),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _kpiCard('Avg Distance', '${o.avgTripMiles.toStringAsFixed(1)} mi', Icons.route_rounded),
            ),
          ],
        ),
      ],
    );
  }

  Widget _kpiCard(String label, String value, IconData icon) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: yellow, size: 18),
          const SizedBox(height: 8),
          Text(
            value,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 24,
              fontWeight: FontWeight.w800,
              letterSpacing: -1,
              height: 1,
            ),
          ),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(color: muted, fontSize: 11)),
        ],
      ),
    );
  }

  Widget _buildHistZoneRow(int rank, ZoneStat zone, double maxPickups) {
    final fraction = zone.avgDailyPickups / maxPickups;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: divider),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 28,
            child: Text(
              '#$rank',
              style: TextStyle(
                color: rank <= 3 ? yellow : muted,
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  zone.zoneName,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 5),
                ClipRRect(
                  borderRadius: BorderRadius.circular(2),
                  child: LinearProgressIndicator(
                    value: fraction,
                    backgroundColor: divider,
                    color: yellow.withValues(alpha: 0.55),
                    minHeight: 3,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  zone.borough,
                  style: const TextStyle(color: muted, fontSize: 10),
                ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                _fmt(zone.avgDailyPickups.round()),
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
              const Text('avg/day', style: TextStyle(color: muted, fontSize: 10)),
            ],
          ),
        ],
      ),
    );
  }

  // Forecast

  Widget _buildForecast() {
    final forecast = _forecast!;
    if (forecast.isEmpty) {
      return const Center(
        child: Text('No forecast data', style: TextStyle(color: muted)),
      );
    }
    final selected = forecast[_selectedHour];
    final q = _searchQuery.toLowerCase().trim();
    final filtered = q.isEmpty
        ? selected.zones
        : selected.zones
            .where((z) =>
                z.zoneName.toLowerCase().contains(q) ||
                z.borough.toLowerCase().contains(q))
            .toList();
    final maxPickupsInHour =
        selected.zones.isNotEmpty ? selected.zones.first.predictedPickups : 1;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      '12-Hour Demand Forecast',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                        fontSize: 15,
                        letterSpacing: -0.3,
                      ),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: yellow.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      '+${selected.hour + 1}h',
                      style: const TextStyle(
                        color: yellow,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              _buildForecastChart(forecast),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: _buildSearchBar(),
        ),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            children: [
              Text(
                'Zones · +${selected.hour + 1}h',
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                  letterSpacing: -0.3,
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '${filtered.length} zones',
                style: const TextStyle(color: muted, fontSize: 11),
              ),
            ],
          ),
        ),
        const SizedBox(height: 6),
        Expanded(
          child: filtered.isEmpty
              ? Center(
                  child: Text(
                    'No zones match "$_searchQuery"',
                    style: const TextStyle(color: muted),
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
                  itemCount: filtered.length,
                  itemBuilder: (_, i) => _buildForecastZoneRow(
                    i + 1,
                    filtered[i],
                    maxPickupsInHour,
                  ),
                ),
        ),
      ],
    );
  }

  Widget _buildSearchBar() {
    return TextField(
      controller: _searchCtrl,
      style: const TextStyle(color: Colors.white, fontSize: 14),
      decoration: InputDecoration(
        hintText: 'Search zone or borough...',
        hintStyle: const TextStyle(color: muted, fontSize: 14),
        prefixIcon: const Icon(Icons.search, color: muted, size: 20),
        suffixIcon: _searchQuery.isNotEmpty
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
    );
  }

  Widget _buildForecastChart(List<ForecastHour> forecast) {
    final maxPickups = forecast.map((h) => h.totalPickups).reduce(max);
    return Container(
      height: 130,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
      decoration: BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: divider),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: forecast.asMap().entries.map((entry) {
          final i = entry.key;
          final h = entry.value;
          final frac = maxPickups > 0 ? h.totalPickups / maxPickups : 0.0;
          final isSelected = i == _selectedHour;
          return Expanded(
            child: GestureDetector(
              onTap: () => setState(() => _selectedHour = i),
              behavior: HitTestBehavior.opaque,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    AnimatedContainer(
                      duration: const Duration(milliseconds: 180),
                      height: 82 * frac + 6,
                      decoration: BoxDecoration(
                        color: isSelected ? yellow : surface2,
                        borderRadius: const BorderRadius.vertical(
                          top: Radius.circular(3),
                        ),
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      '+${h.hour + 1}h',
                      style: TextStyle(
                        color: isSelected ? yellow : muted,
                        fontSize: 9,
                        fontWeight:
                            isSelected ? FontWeight.w700 : FontWeight.normal,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  void _showZonePopup(ZoneForecast zone) {
    final hourlyData = _forecast!
        .map((h) {
          final match = h.zones.firstWhere(
            (z) => z.zoneId == zone.zoneId,
            orElse: () => ZoneForecast(
              zoneId: zone.zoneId,
              zoneName: zone.zoneName,
              borough: zone.borough,
              predictedPickups: 0,
              intensity: 0,
            ),
          );
          return (h.hour, match.predictedPickups);
        })
        .toList();

    showModalBottomSheet(
      context: context,
      backgroundColor: card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => _ZoneDetailSheet(zone: zone, hourlyData: hourlyData),
    );
  }

  Widget _buildForecastZoneRow(int rank, ZoneForecast zone, int maxPickups) {
    final fraction = maxPickups > 0 ? zone.predictedPickups / maxPickups : 0.0;
    return GestureDetector(
      onTap: () => _showZonePopup(zone),
      child: Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: divider),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 28,
            child: Text(
              '#$rank',
              style: TextStyle(
                color: rank <= 3 ? yellow : muted,
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  zone.zoneName,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 5),
                ClipRRect(
                  borderRadius: BorderRadius.circular(2),
                  child: LinearProgressIndicator(
                    value: fraction,
                    backgroundColor: divider,
                    color: yellow.withValues(alpha: 0.55),
                    minHeight: 3,
                  ),
                ),
                const SizedBox(height: 3),
                Text(zone.borough, style: const TextStyle(color: muted, fontSize: 10)),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '${zone.predictedPickups}',
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
              const Text('predicted', style: TextStyle(color: muted, fontSize: 10)),
            ],
          ),
        ],
      ),
      ),
    );
  }

  // Helpers

  Widget _sectionHeader(String title) => Text(
    title,
    style: const TextStyle(
      color: Colors.white,
      fontWeight: FontWeight.w700,
      fontSize: 15,
      letterSpacing: -0.3,
    ),
  );

  String _fmt(int n) {
    if (n >= 1000000000) return '${(n / 1000000000).toStringAsFixed(1)}B';
    if (n >= 1000000) return '${(n / 1000000).toStringAsFixed(0)}M';
    if (n >= 1000) return '${(n / 1000).toStringAsFixed(0)}K';
    return '$n';
  }
}

// Zone detail bottom sheet

class _ZoneDetailSheet extends StatelessWidget {
  final ZoneForecast zone;
  final List<(int, int)> hourlyData; // (hour, predictedPickups)

  const _ZoneDetailSheet({required this.zone, required this.hourlyData});

  @override
  Widget build(BuildContext context) {
    final maxPickups = hourlyData.map((e) => e.$2).fold(0, max);
    final peakEntry = hourlyData.reduce((a, b) => a.$2 >= b.$2 ? a : b);
    final total = hourlyData.fold(0, (s, e) => s + e.$2);

    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: divider,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(
            zone.zoneName,
            style: const TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w800,
              fontSize: 18,
              letterSpacing: -0.5,
            ),
          ),
          const SizedBox(height: 4),
          Text(zone.borough, style: const TextStyle(color: muted, fontSize: 13)),
          const SizedBox(height: 20),
          const Text(
            'Predicted demand · 12h',
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w600,
              fontSize: 13,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 12),
          _build12hChart(maxPickups),
          const SizedBox(height: 20),
          Row(
            children: [
              _statChip(
                'Peak hour',
                '+${peakEntry.$1 + 1}h',
                Icons.trending_up_rounded,
              ),
              const SizedBox(width: 10),
              _statChip(
                'Total (12h)',
                '$total',
                Icons.numbers_rounded,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _build12hChart(int maxPickups) {
    return SizedBox(
      height: 110,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: hourlyData.map((entry) {
          final frac = maxPickups > 0 ? entry.$2 / maxPickups : 0.0;
          return Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 2),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Container(
                    height: 80 * frac + 4,
                    decoration: BoxDecoration(
                      color: yellow,
                      borderRadius: const BorderRadius.vertical(
                        top: Radius.circular(3),
                      ),
                    ),
                  ),
                  const SizedBox(height: 5),
                  Text(
                    '+${entry.$1 + 1}h',
                    style: const TextStyle(color: muted, fontSize: 9),
                  ),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _statChip(String label, String value, IconData icon) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: surface2,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: divider),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: yellow, size: 14),
            const SizedBox(height: 6),
            Text(
              value,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
                fontSize: 15,
              ),
            ),
            Text(label, style: const TextStyle(color: muted, fontSize: 10)),
          ],
        ),
      ),
    );
  }
}

// Type toggle

class _TypeToggle extends StatelessWidget {
  final bool isFhvhv;
  final ValueChanged<bool> onChanged;

  const _TypeToggle({required this.isFhvhv, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 32,
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


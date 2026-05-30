import 'package:flutter/material.dart';

import 'screens/map.dart';
import 'screens/cameras.dart';
import 'screens/insights.dart';
import 'screens/tips.dart';
import 'screens/rolly.dart';
import 'services/backend_cameras.dart';

void main() {
  runApp(const MuseekarApp());
}

class MuseekarApp extends StatelessWidget {
  const MuseekarApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Museekar',
      theme: ThemeData(brightness: Brightness.dark),
      home: const MainNavigation(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class MainNavigation extends StatefulWidget {
  const MainNavigation({super.key});

  @override
  State<MainNavigation> createState() => _MainNavigationState();
}

class _MainNavigationState extends State<MainNavigation> {
  int _selectedIndex = 2;
  TrafficCamera? _selectedCamera;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBody: true,
      body: IndexedStack(
        index: _selectedIndex,
        children: [
          const Insights(),
          const Tips(),
          MapOverviewMainScreen(
            onCameraSelected: openCamera,
          ),
          CamerasMainScreen(
            initialCamera: _selectedCamera,
          ),
          const Rolly(),
        ],
      ),
      bottomNavigationBar: _PillNavBar(
        selectedIndex: _selectedIndex,
        onTap: (i) => setState(() => _selectedIndex = i),
      ),
    );
  }

  void openCamera(TrafficCamera cam) {
    setState(() {
      _selectedCamera = cam;
      _selectedIndex = 3; // Cameras tab
    });
  }
}

// Pill nav bar 

const _icons = <(IconData, IconData)>[
  (Icons.auto_graph_outlined,       Icons.auto_graph_rounded),
  (Icons.tips_and_updates_outlined, Icons.tips_and_updates_rounded),
  (Icons.map_outlined,              Icons.map_rounded),
  (Icons.videocam_outlined,         Icons.videocam_rounded),
  (Icons.pets_rounded,              Icons.pets_rounded),
];

class _PillNavBar extends StatelessWidget {
  final int selectedIndex;
  final ValueChanged<int> onTap;

  const _PillNavBar({required this.selectedIndex, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final bottomPadding = MediaQuery.of(context).padding.bottom;
    const height  = 52.0;
    const margin  = 32.0;  // horizontal margin each side
    const vMargin = 0.0;  // above safe area

    return Padding(
      padding: EdgeInsets.fromLTRB(margin, 0, margin, vMargin + bottomPadding),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final totalWidth = constraints.maxWidth;
          final itemWidth  = totalWidth / _icons.length;

          return Container(
            height: height,
            decoration: BoxDecoration(
              color: const Color.fromARGB(255, 19, 19, 19),
              borderRadius: BorderRadius.circular(height / 2),
              border: Border.all(
                color: Colors.white.withValues(alpha: 0.07),
                width: 1,
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color.fromARGB(255, 0, 0, 0).withValues(alpha: 0.45),
                  blurRadius: 24,
                  offset: const Offset(0, 8),
                ),
              ],
            ),
            child: Stack(
              children: [
                // Sliding yellow indicator
                TweenAnimationBuilder<double>(
                  tween: Tween(
                    begin: selectedIndex.toDouble(),
                    end: selectedIndex.toDouble(),
                  ),
                  duration: const Duration(milliseconds: 260),
                  curve: Curves.easeInOutCubic,
                  builder: (context, value, child) {
                    const pad = 5.0;
                    return Positioned(
                      left: value * itemWidth + pad,
                      top: pad,
                      child: Container(
                        width: itemWidth - pad * 2,
                        height: height - pad * 2,
                        decoration: BoxDecoration(
                          color: const Color.fromARGB(255, 238, 192, 26),
                          borderRadius: BorderRadius.circular((height - pad * 2) / 2),
                        ),
                      ),
                    );
                  },
                ),

                // Icons
                Row(
                  children: List.generate(_icons.length, (i) {
                    final selected = i == selectedIndex;
                    return Expanded(
                      child: GestureDetector(
                        onTap: () => onTap(i),
                        behavior: HitTestBehavior.opaque,
                        child: Center(
                          child: i == 4
                            ? Image.asset(
                                'assets/rolly_icon.png',
                                width: 22,
                                height: 22,
                                color: selected
                                    ? Colors.black
                                    : Colors.white.withValues(alpha: 0.38),
                                colorBlendMode: BlendMode.srcIn,
                              )
                            : Icon(
                                selected ? _icons[i].$2 : _icons[i].$1,
                                color: selected
                                    ? Colors.black
                                    : Colors.white.withValues(alpha: 0.38),
                                size: 22,
                              ),
                        ),
                      ),
                    );
                  }),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../app_theme.dart';
import '../services/backend_config.dart';
import '../constants.dart';


class Settings extends StatefulWidget {
  const Settings({super.key});

  @override
  State<Settings> createState() => _SettingsState();
}

class _SettingsState extends State<Settings> {
  final TextEditingController _backendUrlController =
      TextEditingController(text: BackendConfig.baseUrl);

  bool _isTestingServer = false;
  bool? _serverOnline;

  @override
  void dispose() {
    _backendUrlController.dispose();
    super.dispose();
  }

  Future<void> _testServer() async {
    setState(() {
      _isTestingServer = true;
      _serverOnline = null;
    });

    try {
      final url = _backendUrlController.text.trim();

      BackendConfig.setBaseUrl(url);

      final online = await BackendConfig.testServer();
      if (!mounted) return;

      setState(() {
        _serverOnline = online;
        _isTestingServer = false;
      });
    } catch (_) {
      if (!mounted) return;

      setState(() {
        _serverOnline = false;
        _isTestingServer = false;
      });
    }
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
          'Settings',
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 22,
            letterSpacing: -0.8,
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 100),
        children: [
          _buildSectionTitle('BACKEND'),

          _buildSettingCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(
                      Icons.dns_outlined,
                      color: yellow,
                      size: 20,
                    ),
                    SizedBox(width: 10),
                    Text(
                      'Backend URL',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w600,
                        fontSize: 14,
                      ),
                    ),
                  ],
                ),

                const SizedBox(height: 12),

                TextField(
                  controller: _backendUrlController,
                  keyboardType: TextInputType.url,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 13,
                  ),
                  decoration: InputDecoration(
                    hintText: BACKEND_URL,
                    hintStyle: const TextStyle(
                      color: muted,
                      fontSize: 13,
                    ),
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 11,
                    ),
                    filled: true,
                    fillColor: bg,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: divider),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: divider),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: yellow),
                    ),
                  ),
                ),

                const SizedBox(height: 12),

                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _isTestingServer ? null : _testServer,
                    icon: _isTestingServer
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: yellow,
                            ),
                          )
                        : const Icon(
                            Icons.wifi_find,
                            size: 18,
                          ),
                    label: Text(
                      _isTestingServer
                          ? 'Querying server...'
                          : 'Test server connection',
                    ),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: yellow,
                      disabledForegroundColor: muted,
                      side: const BorderSide(color: divider),
                      padding: const EdgeInsets.symmetric(vertical: 11),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  ),
                ),

                if (_serverOnline != null) ...[
                  const SizedBox(height: 12),
                  _buildServerStatus(),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Padding(
      padding: const EdgeInsets.only(
        left: 4,
        top: 6,
        bottom: 8,
      ),
      child: Text(
        title,
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: muted,
          letterSpacing: 0.6,
        ),
      ),
    );
  }

  Widget _buildSettingCard({required Widget child}) {
    return Container(
      padding: const EdgeInsets.all(14),
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: divider),
      ),
      child: child,
    );
  }

  Widget _buildServerStatus() {
    final online = _serverOnline!;

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 10,
        vertical: 8,
      ),
      decoration: BoxDecoration(
        color: online
            ? Colors.green.withValues(alpha: 0.10)
            : Colors.red.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: online
              ? Colors.green.withValues(alpha: 0.25)
              : Colors.red.withValues(alpha: 0.25),
        ),
      ),
      child: Row(
        children: [
          Icon(
            online ? Icons.check_circle : Icons.error_outline,
            size: 18,
            color: online ? Colors.greenAccent : Colors.redAccent,
          ),
          const SizedBox(width: 8),
          Text(
            online ? 'Server online' : 'Server offline',
            style: TextStyle(
              color: online ? Colors.greenAccent : Colors.redAccent,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
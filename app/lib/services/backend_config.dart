import 'dart:convert';
import 'package:http/http.dart' as http;

import '../constants.dart';

class BackendConfig {
  static String baseUrl = BACKEND_URL;

  static void setBaseUrl(String url) {
    baseUrl = url.trim().replaceAll(RegExp(r'/$'), '');
  }

  static Future<bool> testServer() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/health'))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode != 200) {
        return false;
      }

      final data = jsonDecode(response.body);

      return data is Map && data['ok'] == true;
    } catch (_) {
      return false;
    }
  }
}


import '../constants.dart';

class BackendConfig {
  static String baseUrl = BACKEND_URL;

  static void setBaseUrl(String url) {
    baseUrl = url.trim().replaceAll(RegExp(r'/$'), '');
  }
}
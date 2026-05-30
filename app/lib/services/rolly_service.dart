import 'dart:convert';

import 'package:http/http.dart' as http;

import '../constants.dart';

class ChatMessage {
  final String role; // 'user' | 'assistant'
  final String content;

  const ChatMessage({required this.role, required this.content});

  Map<String, dynamic> toJson() => {'role': role, 'content': content};
}

// Singleton so history survives screen navigation.
class RollyService {
  static final RollyService _instance = RollyService._internal();
  factory RollyService() => _instance;
  RollyService._internal();

  // Single source of truth for the conversation, read directly by the UI.
  final List<ChatMessage> history = [];

  // Sends [message] to the backend together with the full history so the LLM
  // has context, then appends both turns to [history].
  Future<String> chat(String message) async {
    final res = await http.post(
      Uri.parse('$BACKEND_URL/api/rolly/chat'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'message': message,
        'history': history.sublist(0, history.length - 1).map((m) => m.toJson()).toList(),
      }),
    );

    if (res.statusCode != 200) {
      throw Exception('HTTP ${res.statusCode}: ${res.body}');
    }

    final reply = jsonDecode(res.body)['response'] as String;
    history.add(ChatMessage(role: 'assistant', content: reply));
    return reply;
  }

  void clear() => history.clear();
}

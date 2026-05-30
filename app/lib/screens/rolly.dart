import 'dart:async';
import 'package:flutter/material.dart';
import '../app_theme.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../services/rolly_service.dart';


class Rolly extends StatefulWidget {
  const Rolly({super.key});
  @override
  State<Rolly> createState() => _RollyState();
}

class _RollyState extends State<Rolly> with WidgetsBindingObserver {
  final _service = RollyService();
  final TextEditingController _ctrl = TextEditingController();
  final ScrollController _scroll = ScrollController();
  final FlutterTts _tts = FlutterTts();
  final SpeechToText _stt = SpeechToText();

  bool _loading = false;
  bool _listening = false;
  bool _sttAvailable = false;
  String? _speakingText;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _stt.initialize().then((ok) => setState(() => _sttAvailable = ok));
    _initTts();
    // When returning to this screen, jump to the last message.
    if (_service.history.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());
    }
  }

  double _lastBottomInset = 0;

  @override
  void didChangeMetrics() {
    final bottomInset = WidgetsBinding
        .instance.platformDispatcher.views.first.viewInsets.bottom;
    if (bottomInset > _lastBottomInset) _scrollToBottom();
    _lastBottomInset = bottomInset;
  }

  Future<void> _initTts() async {
    await _tts.setLanguage('en-US');
    await _tts.setSpeechRate(0.55);
    await _tts.setPitch(1.1);
    // await _tts.setVoice({'name': 'Karen', 'locale': 'en-AU'});
    // speak() returns immediately; this fires when the audio actually ends.
    _tts.setCompletionHandler(() {
      if (mounted) setState(() => _speakingText = null);
    });
    // final voices = await _tts.getVoices;                                                                                                                       
    // for (final v in voices) print(v); 
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _ctrl.dispose();
    _scroll.dispose();
    _tts.stop();
    _stt.stop();
    super.dispose();
  }

  Future<void> _send(String text) async {
    text = text.trim();
    if (text.isEmpty || _loading) return;
    _ctrl.clear();

    // Add user message immediately so it appears before waiting for reply.
    setState(() {
      _service.history.add(ChatMessage(role: 'user', content: text));
      _loading = true;
    });
    _scrollToBottom();

    await _service.chat(text); // appends assistant reply to service.history

    setState(() => _loading = false);
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _toggleListen() async {
    if (_listening) {
      await _stt.stop();
      setState(() => _listening = false);
      return;
    }
    setState(() => _listening = true);
    // Uses the native speech recognizer (Android, IOS).
    await _stt.listen(
      onResult: (r) => setState(() => _ctrl.text = r.recognizedWords),
      listenOptions: SpeechListenOptions(
        autoPunctuation: true,
        cancelOnError: true,
      ),
    );
  }

  Future<void> _speak(String text) async {
    if (_speakingText != null) return; // ignore taps while already speaking
    setState(() => _speakingText = text);
    await _tts.speak(text); // non-blocking; completion handler resets _speakingText
  }

  @override
  Widget build(BuildContext context) {
    final history = _service.history;
    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        backgroundColor: bg,
        elevation: 0,
        scrolledUnderElevation: 0,
        titleSpacing: 20,
        centerTitle: true,
        title: const Text(
          'Rolly',
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 22,
            letterSpacing: -0.8,
          ),
        ),
        actions: [
          if (history.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.delete_outline, color: muted),
              tooltip: 'Clear chat',
              onPressed: () => setState(() => _service.clear()),
            ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(height: 1, color: divider),
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: history.isEmpty && !_loading
                ? _buildEmptyState()
                : _buildMessageList(history),
          ),
          _buildInputBar(),
        ],
      ),
    );
  }

  static const _suggestions = [
    'Where should I go right now? I drive yellow taxi.',
    'Best zones for FHV pickups next hour?',
    'Best tip zones for yellow taxi historically?',
    'Where do yellow taxis pick up most in the morning?',
    'Any events on May 15th 2026?',
    'What tip can I expect at JFK Airport?',
    'Top demand zones in 3 hours? FHV.',
    'Best zones for FHV drivers at night historically?',
    'Where do FHV drivers get the best tips historically?',
    'How is LaGuardia Airport for FHV in the next 3 hours?',
    'Tell me more about JFK Airport',
  ];

  Widget _buildEmptyState() {
    return Column(
      children: [
        const SizedBox(height: 35),
        Image.asset('assets/rolly.png', width: 128, height: 128),
        const SizedBox(height: 14),
        const Text(
          'Hi! I\'m Rolly',
          style: TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.bold,
            color: Colors.white,
            letterSpacing: -0.5,
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'Ask me about NYC taxi zones,\ntips, or demand patterns.',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 14, color: muted),
        ),
        const SizedBox(height: 24),
        Expanded(
          child: ListView.separated(
            padding: EdgeInsets.fromLTRB(
              20, 0, 20,
              MediaQuery.of(context).padding.bottom + 16,
            ),
            itemCount: _suggestions.length,
            separatorBuilder: (_, __) => const SizedBox(height: 10),
            itemBuilder: (_, i) => _SuggestionChip(
              text: _suggestions[i],
              onTap: () => _send(_suggestions[i]),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildMessageList(List<ChatMessage> history) {
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      itemCount: history.length + (_loading ? 1 : 0),
      itemBuilder: (_, i) {
        if (i == history.length) return _buildTypingBubble();
        return _buildBubble(history[i]);
      },
    );
  }

  Widget _buildBubble(ChatMessage msg) {
    final isUser = msg.role == 'user';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (!isUser) ...[
            Image.asset('assets/rolly.png', width: 30, height: 30, fit: BoxFit.contain),
            const SizedBox(width: 6),
          ],
          Flexible(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: isUser ? yellow : card,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(18),
                  topRight: const Radius.circular(18),
                  bottomLeft: Radius.circular(isUser ? 18 : 4),
                  bottomRight: Radius.circular(isUser ? 4 : 18),
                ),
                border: isUser ? null : Border.all(color: divider),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  isUser
                      ? Text(
                          msg.content,
                          style: const TextStyle(
                            color: Colors.black,
                            fontSize: 15,
                            height: 1.4,
                            fontWeight: FontWeight.w600,
                          ),
                        )
                      : MarkdownBody(
                          data: msg.content,
                          styleSheet: MarkdownStyleSheet(
                            p: const TextStyle(
                              color: Colors.white,
                              fontSize: 15,
                              height: 1.4,
                            ),
                            strong: const TextStyle(
                              color: Colors.white,
                              fontSize: 15,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                  if (!isUser) ...[
                    const SizedBox(height: 6),
                    GestureDetector(
                      onTap: () => _speak(msg.content),
                      child: Icon(
                        _speakingText == msg.content
                            ? Icons.stop_circle_outlined
                            : Icons.volume_up_outlined,
                        size: 16,
                        color: muted,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          if (isUser) const SizedBox(width: 6),
        ],
      ),
    );
  }

  Widget _buildTypingBubble() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Image.asset('assets/rolly.png', width: 30, height: 30, fit: BoxFit.contain),
          const SizedBox(width: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: card,
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(18),
                topRight: Radius.circular(18),
                bottomRight: Radius.circular(18),
                bottomLeft: Radius.circular(4),
              ),
              border: Border.all(color: divider),
            ),
            child: const _ThinkingText(),
          ),
        ],
      ),
    );
  }

  Widget _buildInputBar() {
    final bottomInset = MediaQuery.of(context).padding.bottom;
    return Container(
      padding: EdgeInsets.fromLTRB(12, 8, 12, 8 + bottomInset),
      decoration: BoxDecoration(
        color: card,
        border: const Border(top: BorderSide(color: divider)),
      ),
      child: Container(
        decoration: BoxDecoration(
          color: surface2,
          borderRadius: BorderRadius.circular(24),
          border: Border.all(color: divider),
        ),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _ctrl,
                textCapitalization: TextCapitalization.sentences,
                onSubmitted: _send,
                enabled: !_loading,
                keyboardAppearance: Brightness.dark,
                style: const TextStyle(color: Colors.white, fontSize: 15),
                decoration: InputDecoration(
                  hintText: _listening ? 'Listening...' : 'Ask Rolly...',
                  hintStyle: const TextStyle(color: muted),
                  border: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(
                      horizontal: 16, vertical: 10),
                ),
              ),
            ),
            if (_sttAvailable)
              _InnerBtn(
                icon: _listening ? Icons.mic : Icons.mic_none,
                color: _listening ? Colors.red : muted,
                onPressed: _loading ? null : _toggleListen,
              ),
            _InnerBtn(
              icon: Icons.send_rounded,
              color: yellow,
              onPressed: _loading ? null : () => _send(_ctrl.text),
            ),
            const SizedBox(width: 4),
          ],
        ),
      ),
    );
  }
}

class _SuggestionChip extends StatelessWidget {
  final String text;
  final VoidCallback onTap;

  const _SuggestionChip({required this.text, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
        decoration: BoxDecoration(
          color: card,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: divider),
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                text,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                  height: 1.3,
                ),
              ),
            ),
            const SizedBox(width: 8),
            const Icon(Icons.arrow_forward_ios_rounded, size: 12, color: muted),
          ],
        ),
      ),
    );
  }
}

class _InnerBtn extends StatelessWidget {
  final IconData icon;
  final Color color;
  final VoidCallback? onPressed;

  const _InnerBtn({
    required this.icon,
    required this.color,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onPressed,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        child: Icon(
          icon,
          color: onPressed == null ? divider : color,
          size: 22,
        ),
      ),
    );
  }
}

class _ThinkingText extends StatefulWidget {
  const _ThinkingText();
  @override
  State<_ThinkingText> createState() => _ThinkingTextState();
}

class _ThinkingTextState extends State<_ThinkingText> {
  // Phrases cycled every 3s once the 2s delay has passed.
  static const _phrases = [
    'purring',
    'hyperthinking',
    'give a sec',
    'on it',
    'almost there',
  ];

  bool _showText = false; // false = show dots, true = show text
  int _phraseIndex = 0;
  int _dotCount = 1;      // cycles 1 → 2 → 3 → 1 …
  Timer? _startTimer;     // fires once after 2s to switch from dots to text
  Timer? _dotTimer;       // advances _dotCount every 500ms
  Timer? _phraseTimer;    // advances _phraseIndex every 3s

  @override
  void initState() {
    super.initState();
    _startTimer = Timer(const Duration(seconds: 2), _activate);
  }

  // Called after 2s: starts the two periodic timers.
  void _activate() {
    if (!mounted) return;
    setState(() => _showText = true);
    _dotTimer = Timer.periodic(const Duration(milliseconds: 500), (_) {
      if (!mounted) return;
      setState(() => _dotCount = _dotCount % 3 + 1);
    });
    _phraseTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (!mounted) return;
      setState(() {
        _phraseIndex = (_phraseIndex + 1) % _phrases.length;
        _dotCount = 1;
      });
    });
  }

  @override
  void dispose() {
    // Cancel all timers to avoid setState calls after the widget is removed.
    _startTimer?.cancel();
    _dotTimer?.cancel();
    _phraseTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_showText) return const _TypingDots();
    // e.g. "purring." → "purring.." → "purring..." → "give a sec." → …
    return Text(
      '${_phrases[_phraseIndex]}${'.' * _dotCount}',
      style: const TextStyle(color: Colors.white, fontSize: 15, height: 1.4),
    );
  }
}

class _TypingDots extends StatefulWidget {
  const _TypingDots();
  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (context, child) => Row(
        mainAxisSize: MainAxisSize.min,
        children: List.generate(3, (i) {
          final t = ((_ctrl.value * 3) - i).clamp(0.0, 1.0);
          final scale = t < 0.5 ? t * 2 : (1.0 - t) * 2;
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 2),
            child: Transform.scale(
              scale: 0.4 + scale * 0.6,
              child: Container(
                width: 8,
                height: 8,
                decoration: const BoxDecoration(
                  shape: BoxShape.circle,
                  color: muted,
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}

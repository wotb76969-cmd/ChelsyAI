import 'dart:convert';

/// Pure logic (no Flutter imports) so it can be unit-tested on the Dart VM.

/// Validates the Chelsy Host address. Only HTTPS (Tailscale Serve) without
/// path, query, credentials or custom port is accepted; plain HTTP is refused.
String validateHostUrl(String raw) {
  final value = raw.trim().replaceFirst(RegExp(r'/+$'), '');
  final uri = Uri.tryParse(value);
  if (uri == null ||
      uri.scheme != 'https' ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      (uri.path.isNotEmpty && uri.path != '/') ||
      uri.hasQuery ||
      uri.hasFragment ||
      (uri.hasPort && uri.port != 443)) {
    throw const FormatException(
        'Укажи HTTPS-адрес Tailscale Serve, например https://laptop.tailnet.ts.net — без пути, порта и параметров.');
  }
  return 'https://${uri.host}';
}

/// Splits a byte stream of newline-delimited JSON into decoded objects.
Stream<Map<String, dynamic>> decodeNdjson(Stream<List<int>> bytes) async* {
  final lines = bytes.transform(utf8.decoder).transform(const LineSplitter());
  await for (final line in lines) {
    final trimmed = line.trim();
    if (trimmed.isEmpty) continue;
    try {
      final value = jsonDecode(trimmed);
      if (value is Map<String, dynamic>) yield value;
    } on FormatException {
      continue;
    }
  }
}

class Conversation {
  Conversation({required this.id, required this.title, required this.updated, required this.favorite});
  final String id;
  final String title;
  final String updated;
  final bool favorite;

  Map<String, dynamic> toJson() => {'id': id, 'title': title, 'updated': updated, 'favorite': favorite};

  factory Conversation.fromJson(Map<String, dynamic> json) => Conversation(
        id: json['id'] as String,
        title: (json['title'] as String?)?.trim().isNotEmpty == true ? json['title'] as String : 'Без названия',
        updated: (json['updated'] ?? '') as String,
        favorite: json['favorite'] == true,
      );
}

class ChatMessage {
  ChatMessage({this.id, required this.role, required this.content, this.rating = 0, this.pending = false});
  final int? id;
  final String role;
  String content;
  int rating;
  bool pending;

  bool get fromUser => role == 'user';

  Map<String, dynamic> toJson() => {'id': id, 'role': role, 'content': content, 'rating': rating};

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        id: json['id'] is int ? json['id'] as int : null,
        role: json['role'] == 'user' ? 'user' : 'assistant',
        content: (json['content'] ?? '') as String,
        rating: json['rating'] is int ? json['rating'] as int : 0,
      );
}

/// Pulse states shown by the Chelsy Pulse indicator.
enum PulseState { ready, generating, searching, syncing, offline }

PulseState pulseFromHost(String? state) {
  switch (state) {
    case 'searching':
      return PulseState.searching;
    case 'syncing':
      return PulseState.syncing;
    case 'offline':
      return PulseState.offline;
    case 'ready':
      return PulseState.ready;
    default:
      return PulseState.generating;
  }
}

/// Only https links from answers may be opened in the browser.
bool isSafeLink(String? href) {
  final uri = Uri.tryParse(href ?? '');
  return uri != null && uri.scheme == 'https' && uri.host.isNotEmpty;
}


/// Concrete Russian explanation of why the host could not be reached.
String explainNetworkError(Object error, String base) {
  final host = Uri.tryParse(base)?.host ?? 'хост';
  final text = error.toString();
  if (text.contains('HandshakeException') || text.contains('CERTIFICATE_VERIFY_FAILED')) {
    return 'Сертификат $host не прошёл проверку. Адрес должен быть именем из Tailscale Serve '
        '(https://имя-пк.tailnet.ts.net); в админке Tailscale включите MagicDNS и HTTPS Certificates.';
  }
  if (text.contains('Failed host lookup') || text.contains('No address associated')) {
    return 'Адрес $host не найден. На телефоне выключен Tailscale или он вошёл в другой аккаунт, '
        'либо в адресе опечатка. Включи Tailscale (Connected) тем же аккаунтом, что и на хосте.';
  }
  if (text.contains('Connection refused')) {
    return 'Компьютер-хост найден, но доступ для устройств на нём не включён. На хосте запусти '
        '«Chelsy AI Host — включить доступ с устройств (Tailscale)».';
  }
  if (text.contains('TimeoutException') || text.contains('timed out')) {
    return 'Хост не отвечает: компьютер выключен или спит, или Tailscale на нём отключён.';
  }
  return 'Хост недоступен. Проверь Tailscale на телефоне и на хосте и что Chelsy AI Host запущен.';
}

/// 502/503/504 from Tailscale Serve: the tunnel works but Chelsy AI Host is not running.
String? explainHttpStatus(int code) => (code == 502 || code == 503 || code == 504)
    ? 'Tailscale на хосте работает, но Chelsy AI Host не запущен или ещё загружается (HTTP $code).'
    : null;

import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class StoredTokens {
  StoredTokens({
    required this.host,
    required this.access,
    required this.refresh,
  });
  final String host;
  final String access;
  final String refresh;
}

/// Own Auth tokens in Android Keystore (0.9.4).
class SecureStore {
  static const _key = 'chelsy_own_auth_v1';
  static final FlutterSecureStorage _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(resetOnError: true),
    iOptions: IOSOptions(
      accessibility: KeychainAccessibility.unlocked_this_device,
      synchronizable: false,
    ),
  );

  static Future<void> saveTokens({
    required String host,
    required String access,
    required String refresh,
  }) async {
    await _storage.write(
      key: _key,
      value: jsonEncode({'host': host, 'access': access, 'refresh': refresh}),
    );
  }

  static Future<StoredTokens?> loadTokens() async {
    final raw = await _storage.read(key: _key);
    if (raw == null || raw.isEmpty) return null;
    try {
      final data = jsonDecode(raw) as Map<String, dynamic>;
      final host = data['host']?.toString() ?? '';
      final access = data['access']?.toString() ?? '';
      final refresh = data['refresh']?.toString() ?? '';
      if (host.isEmpty || refresh.isEmpty) return null;
      return StoredTokens(host: host, access: access, refresh: refresh);
    } catch (_) {
      return null;
    }
  }

  static Future<void> clearTokens() => _storage.delete(key: _key);
}

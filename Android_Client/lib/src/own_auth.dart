import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'secure_storage.dart';

/// Own Host Auth (0.9.4). Replaces Supabase Auth for productive login.
class OwnAuth {
  OwnAuth({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  String? accessToken;
  String? refreshToken;
  String? email;
  String? userId;
  String host = '';

  Future<void> login(String hostUrl, String email, String password) async {
    host = hostUrl.replaceAll(RegExp(r'/$'), '');
    final resp = await _client
        .post(
          Uri.parse('$host/api/v3/auth/login'),
          headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
          body: jsonEncode({
            'email': email.trim(),
            'password': password,
            'device_label': 'android',
          }),
        )
        .timeout(const Duration(seconds: 20));
    final data = jsonDecode(resp.body.isEmpty ? '{}' : resp.body) as Map<String, dynamic>;
    if (resp.statusCode >= 400) {
      throw AuthFailure((data['message'] ?? data['error'] ?? 'Ошибка входа').toString());
    }
    accessToken = data['access_token'] as String?;
    refreshToken = data['refresh_token'] as String?;
    final user = data['user'] as Map<String, dynamic>? ?? {};
    this.email = (user['email'] ?? email).toString();
    userId = user['id']?.toString();
    if (accessToken == null || refreshToken == null) {
      throw AuthFailure('Нет токенов сессии');
    }
    await SecureStore.saveTokens(host: host, access: accessToken!, refresh: refreshToken!);
  }

  Future<bool> resume() async {
    final stored = await SecureStore.loadTokens();
    if (stored == null) return false;
    host = stored.host;
    refreshToken = stored.refresh;
    try {
      final resp = await _client
          .post(
            Uri.parse('$host/api/v3/auth/refresh'),
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            body: jsonEncode({'refresh_token': refreshToken}),
          )
          .timeout(const Duration(seconds: 20));
      final data = jsonDecode(resp.body.isEmpty ? '{}' : resp.body) as Map<String, dynamic>;
      if (resp.statusCode >= 400) {
        await SecureStore.clearTokens();
        return false;
      }
      accessToken = data['access_token'] as String?;
      refreshToken = data['refresh_token'] as String? ?? refreshToken;
      final user = data['user'] as Map<String, dynamic>? ?? {};
      email = user['email']?.toString() ?? email;
      userId = user['id']?.toString() ?? userId;
      if (accessToken == null) return false;
      await SecureStore.saveTokens(host: host, access: accessToken!, refresh: refreshToken!);
      return true;
    } on SocketException {
      return false;
    }
  }

  Future<String> token() async {
    if (accessToken == null) {
      final ok = await resume();
      if (!ok || accessToken == null) {
        throw AuthFailure('Нужно войти');
      }
    }
    return accessToken!;
  }

  Future<void> logout() async {
    try {
      if (accessToken != null && host.isNotEmpty) {
        await _client.post(
          Uri.parse('$host/api/v3/auth/logout'),
          headers: {
            'Authorization': 'Bearer $accessToken',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: '{}',
        );
      }
    } catch (_) {}
    accessToken = null;
    refreshToken = null;
    await SecureStore.clearTokens();
  }
}

class AuthFailure implements Exception {
  AuthFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

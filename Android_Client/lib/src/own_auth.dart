import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'secure_storage.dart';
import 'logic.dart';

/// Own Host Auth (0.9.4). Replaces Supabase Auth for productive login.
class OwnAuth {
  OwnAuth({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  String? accessToken;
  String? refreshToken;
  String? email;
  String? userId;
  String host = '';
  DateTime _expires = DateTime.fromMillisecondsSinceEpoch(0);
  Future<bool>? _refreshing;

  Future<http.Response> _post(
    Uri uri, {
    required Map<String, String> headers,
    required String body,
  }) async {
    final request = http.Request('POST', uri)
      ..followRedirects = false
      ..headers.addAll(headers)
      ..body = body;
    final result = await http.Response.fromStream(await _client.send(request));
    if (result.statusCode >= 300 && result.statusCode < 400) {
      throw AuthFailure('Перенаправление Host отклонено.');
    }
    return result;
  }

  Future<void> login(String hostUrl, String email, String password) async {
    host = validateHostUrl(hostUrl);
    final resp = await _post(
      Uri.parse('$host/api/v3/auth/login'),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: jsonEncode({
        'email': email.trim(),
        'password': password,
        'device_label': Platform.isIOS ? 'iOS' : 'Android',
      }),
    ).timeout(const Duration(seconds: 20));
    final data =
        jsonDecode(resp.body.isEmpty ? '{}' : resp.body)
            as Map<String, dynamic>;
    if (resp.statusCode >= 400) {
      throw AuthFailure(
        (data['message'] ?? data['error'] ?? 'Ошибка входа').toString(),
      );
    }
    _expires = DateTime.now().add(
      Duration(seconds: (data['access_expires_in'] as int? ?? 600) - 30),
    );
    accessToken = data['access_token'] as String?;
    refreshToken = data['refresh_token'] as String?;
    final user = data['user'] as Map<String, dynamic>? ?? {};
    this.email = (user['email'] ?? email).toString();
    userId = user['id']?.toString();
    if (accessToken == null || refreshToken == null) {
      throw AuthFailure('Нет токенов сессии');
    }
    await SecureStore.saveTokens(
      host: host,
      access: accessToken!,
      refresh: refreshToken!,
    );
  }

  Future<bool> resume() async {
    final stored = await SecureStore.loadTokens();
    if (stored == null) return false;
    host = validateHostUrl(stored.host);
    refreshToken = stored.refresh;
    accessToken = stored.access.isEmpty ? null : stored.access;
    try {
      final resp = await _post(
        Uri.parse('$host/api/v3/auth/refresh'),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: jsonEncode({'refresh_token': refreshToken}),
      ).timeout(const Duration(seconds: 12));
      final data =
          jsonDecode(resp.body.isEmpty ? '{}' : resp.body)
              as Map<String, dynamic>;
      if (resp.statusCode == 401) {
        // Only clear on definitive auth rejection (SEC-02 revoke / invalid refresh).
        await SecureStore.clearTokens();
        accessToken = null;
        refreshToken = null;
        return false;
      }
      if (resp.statusCode >= 400) {
        // Transient server error: keep persisted refresh for the next attempt.
        return accessToken != null && accessToken!.isNotEmpty;
      }
      _expires = DateTime.now().add(
        Duration(seconds: (data['access_expires_in'] as int? ?? 600) - 30),
      );
      accessToken = data['access_token'] as String?;
      refreshToken = data['refresh_token'] as String? ?? refreshToken;
      final user = data['user'] as Map<String, dynamic>? ?? {};
      email = user['email']?.toString() ?? email;
      userId = user['id']?.toString() ?? userId;
      if (accessToken == null) return false;
      await SecureStore.saveTokens(
        host: host,
        access: accessToken!,
        refresh: refreshToken!,
      );
      return true;
    } on SocketException {
      return accessToken != null && accessToken!.isNotEmpty;
    } on TimeoutException {
      return accessToken != null && accessToken!.isNotEmpty;
    } on http.ClientException {
      return accessToken != null && accessToken!.isNotEmpty;
    } catch (_) {
      return accessToken != null && accessToken!.isNotEmpty;
    }
  }

  Future<String> token() async {
    if (accessToken == null || DateTime.now().isAfter(_expires)) {
      final ok = await (_refreshing ??= resume().whenComplete(
        () => _refreshing = null,
      ));
      if (!ok || accessToken == null) {
        throw AuthFailure('Нужно войти');
      }
    }
    return accessToken!;
  }

  Future<void> logout() async {
    try {
      if (accessToken != null && host.isNotEmpty) {
        await _post(
          Uri.parse('$host/api/v3/auth/logout'),
          headers: {
            'Authorization': 'Bearer $accessToken',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: '{}',
        ).timeout(const Duration(seconds: 8));
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

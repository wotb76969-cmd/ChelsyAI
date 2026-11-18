import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:material_ui/material_ui.dart';
import 'package:share_plus/share_plus.dart';
import 'api.dart';
import 'own_auth.dart';

class DocumentsScreen extends StatefulWidget {
  const DocumentsScreen({super.key, required this.auth});
  final OwnAuth auth;
  @override
  State<DocumentsScreen> createState() => _DocumentsState();
}

class _DocumentsState extends State<DocumentsScreen> {
  final prompt = TextEditingController();
  final client = http.Client();
  List<Map<String, dynamic>> files = [];
  bool busy = false;
  String message = '';
  String? repeatKey;
  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    client.close();
    prompt.dispose();
    super.dispose();
  }

  Future<http.Response> call(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    final req =
        http.Request(method, Uri.parse('${widget.auth.host}/api/v3$path'))
          ..followRedirects = false
          ..headers.addAll({
            'Authorization': 'Bearer ${await widget.auth.token()}',
            'Accept': 'application/json',
          });
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final resp = await client
        .send(req)
        .then(http.Response.fromStream)
        .timeout(const Duration(minutes: 5));
    if (resp.statusCode < 200 || resp.statusCode >= 300) {
      throw Exception('Host: HTTP ${resp.statusCode}');
    }
    return resp;
  }

  Future<void> load() async {
    try {
      final data = jsonDecode(
        utf8.decode((await call('GET', '/artifacts')).bodyBytes),
      );
      if (mounted) {
        setState(
          () => files = List<Map<String, dynamic>>.from(data['artifacts']),
        );
      }
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    }
  }

  Future<void> generate() async {
    if (prompt.text.trim().isEmpty) return;
    setState(() {
      busy = true;
      message = 'Host обрабатывает запрос…';
    });
    try {
      repeatKey ??= newRequestId();
      final r = await call('POST', '/mind/run', {
        'message': prompt.text,
        'idempotency_key': repeatKey,
      });
      final data = jsonDecode(utf8.decode(r.bodyBytes));
      repeatKey = null;
      if (mounted) setState(() => message = data['answer'].toString());
      await load();
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> share(Map<String, dynamic> file) async {
    try {
      final bytes = (await call(
        'GET',
        '/artifacts/${file['id']}/download',
      )).bodyBytes;
      if (!mounted) return;
      final box = context.findRenderObject() as RenderBox;
      await SharePlus.instance.share(
        ShareParams(
          files: [XFile.fromData(bytes, mimeType: file['mime'])],
          fileNameOverrides: [file['filename']],
          sharePositionOrigin: box.localToGlobal(Offset.zero) & box.size,
        ),
      );
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Chelsy Mind')),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TextField(
          controller: prompt,
          maxLength: 8000,
          maxLines: 4,
          enabled: !busy,
          onChanged: (_) => repeatKey = null,
          decoration: const InputDecoration(
            labelText: 'Сообщение или описание файла',
          ),
        ),
        FilledButton(
          onPressed: busy ? null : generate,
          child: const Text('Отправить'),
        ),
        if (message.isNotEmpty) SelectableText(message),
        TextButton(onPressed: load, child: const Text('Обновить мои файлы')),
        for (final file in files)
          ListTile(
            title: Text(file['title'].toString()),
            subtitle: Text('${file['format']} · ${file['size_bytes']} байт'),
            trailing: IconButton(
              icon: const Icon(Icons.ios_share),
              tooltip: 'Сохранить или поделиться',
              onPressed: () => share(file),
            ),
          ),
      ],
    ),
  );
}

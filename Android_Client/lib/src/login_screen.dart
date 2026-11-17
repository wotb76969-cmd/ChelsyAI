import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'aurora.dart';
import 'logic.dart';
import 'own_auth.dart';
import 'theme.dart';

/// Sign-in with email/password against Chelsy Host api/v3 (0.9.4).
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.onSignedIn, required this.auth});
  final VoidCallback onSignedIn;
  final OwnAuth auth;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _host = TextEditingController();
  bool _busy = false;
  bool _hide = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) {
      if (mounted) setState(() => _host.text = p.getString('chelsy_host') ?? '');
    });
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _host.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    String host;
    try {
      host = validateHostUrl(_host.text);
    } on FormatException catch (e) {
      setState(() => _error = e.message);
      return;
    }
    if (_password.text.length < 15) {
      setState(() => _error = 'Пароль должен содержать не менее 15 символов.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.auth.login(host, _email.text.trim(), _password.text);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('chelsy_host', host);
      _password.clear();
      widget.onSignedIn();
    } on AuthFailure catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = 'Нет соединения с Chelsy Host. Проверь адрес и сеть.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SizedBox(height: 12),
                  Text('Chelsy AI', style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 8),
                  Text('Вход на свой Host (HTTPS)', style: Theme.of(context).textTheme.bodyMedium),
                  const SizedBox(height: 20),
                  const AuroraBand(height: 3),
                  const SizedBox(height: 20),
                  TextField(
                    controller: _host,
                    decoration: const InputDecoration(labelText: 'Адрес Host (https://…)'),
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _email,
                    decoration: const InputDecoration(labelText: 'Email'),
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.username, AutofillHints.email],
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _password,
                    obscureText: _hide,
                    decoration: InputDecoration(
                      labelText: 'Пароль',
                      suffixIcon: IconButton(
                        tooltip: _hide ? 'Показать' : 'Скрыть',
                        onPressed: () => setState(() => _hide = !_hide),
                        icon: Icon(_hide ? Icons.visibility : Icons.visibility_off),
                      ),
                    ),
                    autofillHints: const [AutofillHints.password],
                    onSubmitted: (_) => _busy ? null : _submit(),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: TextStyle(color: ChelsyColors.danger)),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: _busy
                        ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Войти'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

import 'package:material_ui/material_ui.dart';

import 'src/chat_screen.dart';
import 'src/login_screen.dart';
import 'src/own_auth.dart';
import 'src/theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final auth = OwnAuth();
  try {
    await auth.resume().timeout(const Duration(seconds: 15));
  } catch (_) {
    // Host timeout / offline must not block app start; tokens stay on device.
  }
  runApp(ChelsyApp(auth: auth));
}

class ChelsyApp extends StatelessWidget {
  const ChelsyApp({super.key, required this.auth});
  final OwnAuth auth;

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'Chelsy AI',
        theme: chelsyTheme(),
        home: AuthGate(auth: auth),
      );
}

class AuthGate extends StatefulWidget {
  const AuthGate({super.key, required this.auth});
  final OwnAuth auth;
  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  bool get _signedIn => widget.auth.accessToken != null;

  @override
  Widget build(BuildContext context) => _signedIn
      ? ChatScreen(auth: widget.auth, onSignedOut: () => setState(() {}))
      : LoginScreen(auth: widget.auth, onSignedIn: () => setState(() {}));
}

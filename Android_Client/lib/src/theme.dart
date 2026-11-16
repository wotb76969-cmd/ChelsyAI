import 'package:material_ui/material_ui.dart';

/// Chelsy AI brand palette (shared with Desktop and Windows Client).
/// "Northern lights" world: polar-night ground, the aurora (violet → lavender →
/// turquoise) appears only where Chelsy is working or the user acts.
class ChelsyColors {
  static const background = Color(0xFF0B0C20); // polar night
  static const panel = Color(0xFF11132B); // first tonal lift
  static const panel2 = Color(0xFF161937); // fields, composer
  static const raised = Color(0xFF1C2046); // user turn, hover
  static const stroke = Color(0xFF262A52);
  static const violet = Color(0xFF6D4AFF);
  static const lavender = Color(0xFFA78BFA);
  static const teal = Color(0xFF21D9DA);
  static const text = Color(0xFFECEBFA); // snow
  static const muted = Color(0xFFA3A6C8); // frost
  static const userBubble = Color(0xFF231D4F);
  static const selected = Color(0xFF2A2160);
  static const codeBg = Color(0xFF0E1029);
  static const danger = Color(0xFFFF8A65);

  /// The aurora: the brand gradient, used only for the horizon band.
  static const aurora = [violet, lavender, teal];
}

ThemeData chelsyTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: ChelsyColors.violet,
    brightness: Brightness.dark,
  ).copyWith(
    primary: ChelsyColors.violet,
    onPrimary: Colors.white, // 5.15:1 on violet
    secondary: ChelsyColors.teal,
    onSecondary: ChelsyColors.background,
    tertiary: ChelsyColors.lavender,
    surface: ChelsyColors.background,
    onSurface: ChelsyColors.text,
    onSurfaceVariant: ChelsyColors.muted,
    surfaceContainerLowest: ChelsyColors.background,
    surfaceContainerLow: ChelsyColors.panel,
    surfaceContainer: ChelsyColors.panel,
    surfaceContainerHigh: ChelsyColors.panel2,
    surfaceContainerHighest: ChelsyColors.raised,
    secondaryContainer: ChelsyColors.selected,
    onSecondaryContainer: ChelsyColors.text,
    outline: ChelsyColors.stroke,
    outlineVariant: ChelsyColors.stroke,
    error: ChelsyColors.danger,
  );
  const body = TextStyle(color: ChelsyColors.text, height: 1.45);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: ChelsyColors.background,
    textTheme: const TextTheme(
      titleLarge: TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: ChelsyColors.text),
      titleMedium: TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: ChelsyColors.text),
      bodyLarge: TextStyle(fontSize: 16, color: ChelsyColors.text, height: 1.5),
      bodyMedium: TextStyle(fontSize: 14, color: ChelsyColors.text, height: 1.45),
      bodySmall: TextStyle(fontSize: 12, color: ChelsyColors.muted, height: 1.4),
      labelLarge: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
      labelSmall: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, letterSpacing: 0.6, color: ChelsyColors.muted),
    ).apply(bodyColor: body.color, displayColor: body.color),
    appBarTheme: const AppBarTheme(
      backgroundColor: ChelsyColors.background,
      surfaceTintColor: Colors.transparent,
      foregroundColor: ChelsyColors.text,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: ChelsyColors.text),
    ),
    drawerTheme: const DrawerThemeData(
      backgroundColor: ChelsyColors.panel,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.horizontal(right: Radius.circular(20))),
    ),
    listTileTheme: const ListTileThemeData(
      iconColor: ChelsyColors.muted,
      textColor: ChelsyColors.text,
      selectedColor: ChelsyColors.text,
      selectedTileColor: ChelsyColors.selected,
      minVerticalPadding: 10,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(12))),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: ChelsyColors.violet,
        foregroundColor: Colors.white,
        disabledBackgroundColor: ChelsyColors.raised,
        disabledForegroundColor: ChelsyColors.muted,
        minimumSize: const Size(48, 48),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(14))),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: ChelsyColors.lavender, minimumSize: const Size(48, 48)),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(foregroundColor: ChelsyColors.muted, minimumSize: const Size(48, 48)),
    ),
    chipTheme: const ChipThemeData(
      backgroundColor: ChelsyColors.panel2,
      selectedColor: ChelsyColors.selected,
      side: BorderSide(color: ChelsyColors.stroke),
      labelStyle: TextStyle(fontSize: 13, color: ChelsyColors.text),
      shape: StadiumBorder(),
    ),
    dividerTheme: const DividerThemeData(color: ChelsyColors.stroke, thickness: 1, space: 1),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: ChelsyColors.teal, linearTrackColor: ChelsyColors.raised),
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: ChelsyColors.lavender,
      selectionColor: ChelsyColors.violet.withValues(alpha: 0.45),
      selectionHandleColor: ChelsyColors.lavender,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: ChelsyColors.panel2,
      hintStyle: const TextStyle(color: ChelsyColors.muted),
      labelStyle: const TextStyle(color: ChelsyColors.muted),
      floatingLabelStyle: const TextStyle(color: ChelsyColors.lavender),
      prefixIconColor: ChelsyColors.muted,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: ChelsyColors.stroke),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: ChelsyColors.stroke),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: ChelsyColors.lavender, width: 1.6),
      ),
    ),
    snackBarTheme: const SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: ChelsyColors.raised,
      contentTextStyle: TextStyle(color: ChelsyColors.text),
    ),
  );
}

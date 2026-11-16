import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

import 'logic.dart';
import 'theme.dart';

/// The aurora horizon: Chelsy Pulse drawn as a thin band along the top edge of
/// the composer. Still and dim when ready, flowing violet→lavender while
/// generating, a turquoise sweep while searching, lavender breathing while
/// syncing, flat coral when the host is offline. One ticker, one gradient;
/// becomes still when the system "remove animations" setting is on.
class AuroraBand extends StatefulWidget {
  const AuroraBand({super.key, required this.state, this.height = 3});
  final PulseState state;
  final double height;

  @override
  State<AuroraBand> createState() => _AuroraBandState();
}

class _AuroraBandState extends State<AuroraBand> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2400));

  bool get _moving => widget.state == PulseState.generating ||
      widget.state == PulseState.searching ||
      widget.state == PulseState.syncing;

  void _sync() {
    final still = MediaQuery.maybeOf(context)?.disableAnimations ?? false;
    if (_moving && !still) {
      if (!_c.isAnimating) _c.repeat();
    } else {
      _c.stop();
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync();
  }

  @override
  void didUpdateWidget(covariant AuroraBand oldWidget) {
    super.didUpdateWidget(oldWidget);
    _sync();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: switch (widget.state) {
        PulseState.ready => 'Chelsy готова',
        PulseState.generating => 'Chelsy отвечает',
        PulseState.searching => 'Chelsy ищет информацию',
        PulseState.syncing => 'Синхронизация',
        PulseState.offline => 'Хост недоступен',
      },
      child: SizedBox(
        height: widget.height,
        width: double.infinity,
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) => CustomPaint(painter: _AuroraPainter(widget.state, _c.value)),
        ),
      ),
    );
  }
}

class _AuroraPainter extends CustomPainter {
  _AuroraPainter(this.state, this.t);
  final PulseState state;
  final double t;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final rrect = RRect.fromRectAndRadius(rect, Radius.circular(size.height));
    final paint = Paint();
    switch (state) {
      case PulseState.offline:
        paint.color = ChelsyColors.danger.withValues(alpha: 0.85);
      case PulseState.ready:
        paint.shader = LinearGradient(colors: [
          ChelsyColors.violet.withValues(alpha: 0.35),
          ChelsyColors.lavender.withValues(alpha: 0.35),
          ChelsyColors.teal.withValues(alpha: 0.35),
        ]).createShader(rect);
      case PulseState.searching:
        final x = t * 1.6 - 0.3;
        paint.shader = LinearGradient(
          colors: [
            ChelsyColors.teal.withValues(alpha: 0.15),
            ChelsyColors.teal,
            ChelsyColors.teal.withValues(alpha: 0.15),
          ],
          stops: [math.max(0, x - 0.25), x.clamp(0, 1).toDouble(), math.min(1, x + 0.25)],
        ).createShader(rect);
      case PulseState.syncing:
        final a = 0.45 + 0.4 * math.sin(t * 2 * math.pi).abs();
        paint.color = ChelsyColors.lavender.withValues(alpha: a);
      case PulseState.generating:
        // The aurora drifts: the gradient slides along the band.
        paint.shader = LinearGradient(
          colors: const [ChelsyColors.violet, ChelsyColors.lavender, ChelsyColors.teal, ChelsyColors.lavender, ChelsyColors.violet],
          tileMode: TileMode.repeated,
          transform: GradientRotation(0),
        ).createShader(Rect.fromLTWH(-size.width * t, 0, size.width * 2, size.height));
    }
    canvas.drawRRect(rrect, paint);
  }

  @override
  bool shouldRepaint(covariant _AuroraPainter old) => old.state != state || old.t != t;
}

import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import 'logic.dart';
import 'theme.dart';

/// One chat message: user bubble or Chelsy's Markdown answer with actions.
class MessageView extends StatelessWidget {
  const MessageView({
    super.key,
    required this.message,
    this.onEdit,
    this.onRegenerate,
    this.onRate,
  });

  final ChatMessage message;
  final VoidCallback? onEdit;
  final VoidCallback? onRegenerate;
  final void Function(int rating)? onRate;

  /// Markdown styles for Chelsy's answers (public for tests).
  static MarkdownStyleSheet markdownStyle() {
    // Built explicitly (not fromTheme): flutter_markdown_plus still targets
    // the legacy flutter/material ThemeData type.
    const body = TextStyle(fontSize: 16, height: 1.55, color: ChelsyColors.text);
    return MarkdownStyleSheet(
      p: body,
      listBullet: body,
      tableBody: body,
      tableHead: body.copyWith(fontWeight: FontWeight.w600),
      strong: const TextStyle(fontWeight: FontWeight.w700),
      em: const TextStyle(fontStyle: FontStyle.italic),
      h1: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: ChelsyColors.text),
      h2: const TextStyle(fontSize: 19, fontWeight: FontWeight.w700, color: ChelsyColors.text),
      h3: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: ChelsyColors.text),
      blockSpacing: 10,
      codeblockPadding: const EdgeInsets.all(12),

      // Code is data: monospace, snow on the deepest night (contrast 16:1). The colour is explicit:
      // without it flutter_markdown_plus falls back to a dark default on this ground. No span
      // background: per-line text backgrounds draw ragged boxes; the block decoration carries it.
      // Bundled JetBrains Mono (ChelsyMono), with the system mono face as fallback.
      code: const TextStyle(fontFamily: 'ChelsyMono', fontFamilyFallback: ['monospace'], fontSize: 13.5, height: 1.5, color: ChelsyColors.text),
      codeblockDecoration: BoxDecoration(
        color: ChelsyColors.codeBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ChelsyColors.stroke),
      ),
      a: const TextStyle(color: ChelsyColors.lavender, decoration: TextDecoration.underline, decorationColor: ChelsyColors.lavender),
      horizontalRuleDecoration: const BoxDecoration(border: Border(top: BorderSide(color: ChelsyColors.stroke))),
      blockquoteDecoration: BoxDecoration(
        color: ChelsyColors.panel2,
        borderRadius: BorderRadius.circular(8),
      ),
    );
  }

  static final _sourceLine = RegExp(r'^\d+\.\s+\[([^\]]*)\]\(([^)\s]+)\)(?:\s+·\s+(\d{4}-\d{2}-\d{2}))?(.*)$');
  static final _sourceHead = RegExp(r'^\*\*(.+?)\*\*$');

  /// Splits the engine's sources footer (`---` + "**Источники из интернета:**" lines)
  /// from the answer body. Returns the body and the parsed groups (public for tests).
  /// Anything that does not look exactly like the footer is left as Markdown.
  static (String, List<SourceGroup>) splitSources(String content) {
    const marker = '\n\n---\n';
    final cut = content.lastIndexOf(marker);
    if (cut < 0) return (content, const []);
    final groups = <SourceGroup>[];
    for (final raw in content.substring(cut + marker.length).split('\n')) {
      final line = raw.trim();
      if (line.isEmpty) continue;
      final head = _sourceHead.firstMatch(line);
      if (head != null) {
        groups.add(SourceGroup(head.group(1)!.replaceAll(RegExp(r':$'), ''), []));
        continue;
      }
      final m = _sourceLine.firstMatch(line);
      if (m == null || groups.isEmpty) return (content, const []);
      final title = m.group(1)!.trim();
      groups.last.items.add(SourceItem(title.isEmpty ? m.group(2)! : title, m.group(2)!, m.group(3), m.group(4)!.trim()));
    }
    if (groups.every((g) => g.items.isEmpty)) return (content, const []);
    return (content.substring(0, cut), groups);
  }

  Future<void> _openLink(BuildContext context, String? href) async {
    if (!isSafeLink(href)) return;
    await launchUrl(Uri.parse(href!), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final maxWidth = width > 900 ? 760.0 : width * 0.9;
    if (message.fromUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxWidth * 0.85),
          child: GestureDetector(
            onLongPress: onEdit,
            child: Container(
              margin: const EdgeInsets.only(top: 10, bottom: 6, left: 40),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
              decoration: const BoxDecoration(
                color: ChelsyColors.userBubble,
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(20),
                  topRight: Radius.circular(20),
                  bottomLeft: Radius.circular(20),
                  bottomRight: Radius.circular(6),
                ),
              ),
              child: SelectableText(message.content, style: const TextStyle(fontSize: 16, height: 1.45, color: ChelsyColors.text)),
            ),
          ),
        ),
      );
    }
    final style = markdownStyle();
    final (body, sources) = message.pending ? (message.content, const <SourceGroup>[]) : splitSources(message.content);
    return Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(9),
              child: Image.asset('chelsy_logo.png', width: 28, height: 28, cacheWidth: 84),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                MarkdownBody(
                  data: body.isEmpty ? '…' : body,
                  selectable: true,
                  styleSheet: style,
                  onTapLink: (text, href, title) => _openLink(context, href),
                ),
                if (sources.isNotEmpty) _Sources(groups: sources, onOpen: (href) => _openLink(context, href)),
                if (!message.pending)
                  Row(children: [
                    _Action(icon: Icons.copy_rounded, label: 'Копировать', onTap: () {
                      Clipboard.setData(ClipboardData(text: message.content));
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Ответ скопирован')));
                    }),
                    if (onRegenerate != null) _Action(icon: Icons.refresh_rounded, label: 'Повторить', onTap: onRegenerate!),
                    if (onRate != null && message.id != null) ...[
                      _Action(
                          icon: message.rating > 0 ? Icons.thumb_up_alt : Icons.thumb_up_alt_outlined,
                          label: 'Хороший ответ',
                          onTap: () => onRate!(1)),
                      _Action(
                          icon: message.rating < 0 ? Icons.thumb_down_alt : Icons.thumb_down_alt_outlined,
                          label: 'Плохой ответ',
                          onTap: () => onRate!(-1)),
                    ],
                  ]),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class SourceItem {
  const SourceItem(this.title, this.url, this.date, this.note);
  final String title;
  final String url;
  final String? date;
  final String note;
}

class SourceGroup {
  SourceGroup(this.title, this.items);
  final String title;
  final List<SourceItem> items;
}

/// Sources under an answer: lavender titles, turquoise tabular dates, one quiet rule above.
class _Sources extends StatelessWidget {
  const _Sources({required this.groups, required this.onOpen});
  final List<SourceGroup> groups;
  final void Function(String href) onOpen;

  static const _tabular = [FontFeature.tabularFigures()];

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.only(top: 8),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: ChelsyColors.stroke))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final g in groups) ...[
          Padding(
            padding: const EdgeInsets.only(top: 6, bottom: 2),
            child: Text(g.title, style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: ChelsyColors.muted)),
          ),
          for (final (i, item) in g.items.indexed)
            InkWell(
              borderRadius: BorderRadius.circular(8),
              onTap: () => onOpen(item.url),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 44),
                child: Row(children: [
                  SizedBox(
                    width: 24,
                    child: Text('${i + 1}.',
                        style: const TextStyle(fontSize: 13.5, color: ChelsyColors.muted, fontFeatures: _tabular)),
                  ),
                  Expanded(
                    child: Text.rich(
                      TextSpan(children: [
                        TextSpan(
                            text: item.title,
                            style: const TextStyle(
                                color: ChelsyColors.lavender,
                                decoration: TextDecoration.underline,
                                decorationColor: ChelsyColors.lavender)),
                        if (item.note.isNotEmpty)
                          TextSpan(text: ' ${item.note}', style: const TextStyle(color: ChelsyColors.muted)),
                      ]),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 14, height: 1.4),
                    ),
                  ),
                  if (item.date != null)
                    Padding(
                      padding: const EdgeInsets.only(left: 10),
                      child: Text(item.date!,
                          key: const ValueKey('source-date'),
                          style: const TextStyle(fontSize: 13, color: ChelsyColors.teal, fontFeatures: _tabular)),
                    ),
                ]),
              ),
            ),
        ],
      ]),
    );
  }
}

class _Action extends StatelessWidget {
  const _Action({required this.icon, required this.label, required this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => IconButton(
        tooltip: label,
        visualDensity: VisualDensity.compact,
        iconSize: 18,
        color: ChelsyColors.muted,
        onPressed: onTap,
        icon: Icon(icon),
      );
}

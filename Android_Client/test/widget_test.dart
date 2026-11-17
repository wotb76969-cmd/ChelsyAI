import 'dart:async';
import 'dart:convert';

import 'dart:io';

import 'package:chelsy_ai_client/src/aurora.dart';
import 'package:chelsy_ai_client/src/local_store.dart';
import 'package:chelsy_ai_client/src/logic.dart';
import 'package:chelsy_ai_client/src/message_view.dart';
import 'package:chelsy_ai_client/src/pulse.dart';
import 'package:chelsy_ai_client/src/theme.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

void main() {
  group('Host URL validation', () {
    test('accepts Host HTTPS origin', () {
      expect(validateHostUrl(' https://chelsy.example.com/ '), 'https://chelsy.example.com');
    });
    test('rejects insecure or ambiguous addresses', () {
      for (final bad in [
        'http://laptop.tailnet.ts.net',
        'https://user:pass@laptop.ts.net',
        'https://laptop.ts.net/api',
        'https://laptop.ts.net:8787',
        'https://laptop.ts.net/?x=1',
        'ftp://laptop.ts.net',
        '',
      ]) {
        expect(() => validateHostUrl(bad), throwsFormatException, reason: bad);
      }
    });
  });

  test('NDJSON stream decoding survives chunk boundaries and junk', () async {
    final payload = '${jsonEncode({'type': 'start'})}\n{"type":"del'
        'ta","text":"При"}\n\nnot-json\n${jsonEncode({'type': 'done', 'text': 'Привет'})}\n';
    final bytes = utf8.encode(payload);
    final chunks = Stream<List<int>>.fromIterable([bytes.sublist(0, 7), bytes.sublist(7, 31), bytes.sublist(31)]);
    final events = await decodeNdjson(chunks).toList();
    expect(events.map((e) => e['type']), ['start', 'delta', 'done']);
    expect(events.last['text'], 'Привет');
  });

  test('local store keeps an offline copy per account and clears it', () async {
    final dir = await Directory.systemTemp.createTemp('chelsy_store');
    final store = LocalStore(Directory('${dir.path}/u1'));
    const id = '11111111-1111-4111-8111-111111111111';
    await store.saveConversations([Conversation(id: id, title: 'Небо', updated: '2026', favorite: true)]);
    await store.saveMessages(id, [
      ChatMessage(id: 1, role: 'user', content: 'Почему небо голубое?'),
      ChatMessage(role: 'assistant', content: 'Рассеяние света.'),
      ChatMessage(role: 'assistant', content: '…', pending: true),
    ]);
    expect((await store.loadConversations()).single.favorite, isTrue);
    final msgs = await store.loadMessages(id);
    expect(msgs.map((m) => m.content), ['Почему небо голубое?', 'Рассеяние света.']);
    expect(await store.loadMessages('../../etc/passwd'), isEmpty);
    await store.clear();
    expect(await store.loadConversations(), isEmpty);
    await dir.delete(recursive: true);
  });

  test('only https links are opened', () {
    expect(isSafeLink('https://docs.python.org'), isTrue);
    expect(isSafeLink('http://example.org'), isFalse);
    expect(isSafeLink('javascript:alert(1)'), isFalse);
    expect(isSafeLink('intent://evil'), isFalse);
    expect(isSafeLink(null), isFalse);
  });

  test('pulse state mapping', () {
    expect(pulseFromHost('searching'), PulseState.searching);
    expect(pulseFromHost('checking'), PulseState.generating);
    expect(pulseFromHost('offline'), PulseState.offline);
  });

  testWidgets('message views render Markdown answer and user bubble', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: chelsyTheme(),
      home: Scaffold(
        body: ListView(children: [
          MessageView(message: ChatMessage(role: 'user', content: 'Почему небо голубое?')),
          MessageView(
            message: ChatMessage(id: 2, role: 'assistant', content: 'Дело в **рассеянии** света.\n\n```python\nprint(1)\n```'),
            onRegenerate: () {},
            onRate: (_) {},
          ),
        ]),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Почему небо голубое?'), findsOneWidget);
    expect(find.byTooltip('Повторить'), findsOneWidget);
    expect(find.byTooltip('Копировать'), findsOneWidget);
  });

  testWidgets('pulse respects reduced motion and settles', (tester) async {
    await tester.pumpWidget(const MediaQuery(
      data: MediaQueryData(disableAnimations: true),
      child: Directionality(textDirection: TextDirection.ltr, child: ChelsyPulse(state: PulseState.generating)),
    ));
    await tester.pumpAndSettle(const Duration(milliseconds: 100), EnginePhase.sendSemanticsUpdate, const Duration(seconds: 2));
    expect(find.byType(ChelsyPulse), findsOneWidget);
  });

  testWidgets('aurora horizon renders every Pulse state and stays still with reduced motion', (tester) async {
    for (final state in PulseState.values) {
      await tester.pumpWidget(MediaQuery(
        data: const MediaQueryData(disableAnimations: true),
        child: Directionality(
          textDirection: TextDirection.ltr,
          child: Center(child: SizedBox(width: 300, child: AuroraBand(state: state))),
        ),
      ));
      await tester.pump(const Duration(milliseconds: 500));
      expect(tester.hasRunningAnimations, isFalse, reason: state.name);
      expect(find.byType(AuroraBand), findsOneWidget);
    }
  });

  test('code blocks in answers use readable snow-on-night text', () {
    final sheet = MessageView.markdownStyle();
    expect(sheet.code?.color, ChelsyColors.text);
    expect((sheet.codeblockDecoration as BoxDecoration).color, ChelsyColors.codeBg);
  });

  test('code style has no ragged span background', () {
    expect(MessageView.markdownStyle().code?.backgroundColor, isNull);
  });

  test('sources footer is split into groups with dates', () {
    const answer = 'Ответ.\n\n---\n**Источники из интернета:**\n'
        '1. [FastAPI 0.120](https://fastapi.tiangolo.com/release-notes/) · 2026-11-12\n'
        '**Из базы знаний:**\n1. [Учебник](https://docs.python.org/3/tutorial/) (личная)';
    final (body, groups) = MessageView.splitSources(answer);
    expect(body, 'Ответ.');
    expect(groups.map((g) => g.title), ['Источники из интернета', 'Из базы знаний']);
    expect(groups.first.items.single.date, '2026-11-12');
    expect(groups.last.items.single.date, isNull);
    expect(groups.last.items.single.note, '(личная)');
    // A plain horizontal rule in an answer is left alone.
    final (keep, none) = MessageView.splitSources('A\n\n---\nB');
    expect(keep, 'A\n\n---\nB');
    expect(none, isEmpty);
  });

  testWidgets('answer with sources shows turquoise dates', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: chelsyTheme(),
      home: Scaffold(
        body: MessageView(
            message: ChatMessage.fromJson(const {
          'role': 'assistant',
          'content': 'Ответ.\n\n---\n**Источники из интернета:**\n1. [FastAPI](https://fastapi.tiangolo.com/) · 2026-11-12',
        })),
      ),
    ));
    final date = tester.widget<Text>(find.byKey(const ValueKey('source-date')));
    expect(date.data, '2026-11-12');
    expect(date.style?.color, ChelsyColors.teal);
    expect(find.text('Источники из интернета'), findsOneWidget);
  });
}

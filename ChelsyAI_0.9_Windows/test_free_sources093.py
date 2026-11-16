"""Free, key-less search: Wikipedia, RSS news, Hacker News, Stack Exchange, PyPI/GitHub, SearXNG.
All HTTP is mocked; formats follow the real public APIs."""
import os
import unittest
from unittest.mock import patch

from knowledge import free_sources as fs
from knowledge.search_manager import SearchManager

WIKI = {'query': {'pages': [
    {'index': 2, 'title': 'Pydantic', 'fullurl': 'https://ru.wikipedia.org/wiki/Pydantic', 'extract': 'Pydantic — библиотека.',
     'touched': '2026-10-01T10:00:00Z'},
    {'index': 1, 'title': 'FastAPI', 'fullurl': 'https://ru.wikipedia.org/wiki/FastAPI',
     'extract': 'FastAPI — веб-фреймворк для Python.', 'touched': '2026-11-01T10:00:00Z'},
]}}

RSS = '''<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Лента</title>
<item><title>В Самаре открыли новый мост</title><link>https://lenta.ru/news/2026/11/16/most/</link>
<description>&lt;p&gt;Мост через Волгу&lt;/p&gt;</description><pubDate>Mon, 16 Nov 2026 09:00:00 +0300</pubDate></item>
<item><title>Курс рубля</title><link>https://lenta.ru/news/2026/11/16/kurs/</link>
<description>Валюта</description><pubDate>Mon, 16 Nov 2026 08:00:00 +0300</pubDate></item>
<item><title>Небезопасная ссылка</title><link>http://example.org/x</link><pubDate>Mon, 16 Nov 2026 07:00:00 +0300</pubDate></item>
</channel></rss>'''

ATOM = '''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Python 3.15 released</title>
<link href="https://blog.python.org/2026/10/python-315.html"/><updated>2026-10-07T00:00:00Z</updated>
<summary>New release</summary></entry></feed>'''


class FreeSourcesTests(unittest.TestCase):
    def setUp(self):
        fs._FEED_CACHE.clear()

    def test_wikipedia_keeps_search_order_and_https_links(self):
        with patch.object(fs, '_get_json', return_value=WIKI) as call:
            items = fs.wikipedia('Что такое FastAPI?')
        self.assertEqual([i['title'] for i in items], ['FastAPI — Википедия', 'Pydantic — Википедия'])
        self.assertEqual(items[0]['published'], '2026-11-01')
        url, params = call.call_args[0]
        self.assertEqual(url, 'https://ru.wikipedia.org/w/api.php')
        self.assertIn('fastapi', params['gsrsearch'])

    def test_rss_and_atom_parsing(self):
        rss = fs._parse_feed(RSS)
        self.assertEqual(len(rss), 2)                       # the http:// link is dropped
        self.assertEqual(rss[0]['published'], '2026-11-16')
        self.assertEqual(rss[0]['excerpt'], 'Мост через Волгу')
        atom = fs._parse_feed(ATOM)
        self.assertEqual(atom[0]['url'], 'https://blog.python.org/2026/10/python-315.html')
        self.assertEqual(atom[0]['published'], '2026-10-07')

    def test_news_filters_feeds_by_question(self):
        with patch.object(fs, '_get_text', return_value=RSS), patch.object(fs, 'hacker_news', return_value=[]):
            items = fs.news('Последние новости Самары')
            latest = fs.news('Последние новости')
        self.assertEqual(items[0]['title'], 'В Самаре открыли новый мост')
        self.assertEqual(len(latest), 2)                    # no topic: freshest headlines

    def test_broken_feed_does_not_break_news(self):
        with patch.object(fs, '_get_text', side_effect=OSError('down')), \
             patch.object(fs, 'hacker_news', return_value=[{'url': 'https://news.ycombinator.com/item?id=1',
                                                            'title': 'x', 'excerpt': '', 'published': '', 'kind': 'news'}]):
            self.assertEqual(len(fs.news('новости FastAPI')), 1)

    def test_programming_and_versions_are_routed(self):
        with patch.object(fs, 'wikipedia', return_value=[]) as wiki, \
             patch.object(fs, 'stack_exchange', return_value=[{'url': 'https://ru.stackoverflow.com/q/1', 'title': 'q'}]) as se, \
             patch.object(fs, 'releases', return_value=[{'url': 'https://pypi.org/project/fastapi/', 'title': 'fastapi 0.120'}]) as rel:
            fs.web('Почему Python пишет ошибку ImportError?')
            self.assertTrue(se.called)
            self.assertFalse(rel.called)
            items = fs.web('Какая последняя версия FastAPI?')
        self.assertTrue(rel.called)
        self.assertEqual(items[0]['title'], 'fastapi 0.120')
        self.assertTrue(wiki.called)

    def test_releases_from_pypi_and_github(self):
        def fake(url, params):
            if 'pypi.org/pypi/fastapi/json' in url:
                return {'info': {'name': 'fastapi', 'version': '0.120.0', 'summary': 'FastAPI framework',
                                 'project_urls': {'Release Notes': 'https://fastapi.tiangolo.com/release-notes/'}}}
            if 'search/repositories' in url:
                return {'items': [{'full_name': 'fastapi/fastapi'}]}
            if 'releases/latest' in url:
                return {'tag_name': '0.120.0', 'html_url': 'https://github.com/fastapi/fastapi/releases/tag/0.120.0',
                        'published_at': '2026-11-12T10:00:00Z', 'body': 'Changes'}
            raise OSError('404')
        with patch.object(fs, '_get_json', side_effect=fake):
            items = fs.releases('последняя версия FastAPI')
        self.assertEqual(items[0]['url'], 'https://fastapi.tiangolo.com/release-notes/')
        self.assertIn('0.120.0', items[0]['excerpt'])
        self.assertEqual(items[1]['published'], '2026-11-12')

    def test_one_source_down_keeps_the_rest(self):
        with patch.object(fs, 'wikipedia', side_effect=OSError('down')), \
             patch.object(fs, 'stack_exchange', return_value=[{'url': 'https://stackoverflow.com/q/1', 'title': 'q'}]):
            self.assertEqual(len(fs.web('python error')), 1)


class SearchManagerChainTests(unittest.TestCase):
    def test_free_sources_need_no_key(self):
        with patch.dict(os.environ, {}, clear=True):
            manager = SearchManager()
            self.assertTrue(manager.configured())
            self.assertEqual(manager.provider(), 'free')
            with patch.object(fs, 'web', return_value=[{'url': 'https://ru.wikipedia.org/wiki/X', 'title': 'X'}]) as web:
                items, note = manager.search('Что такое X?')
        self.assertTrue(web.called)
        self.assertEqual(note, '')
        self.assertEqual(len(items), 1)

    def test_searxng_first_then_free_fallback(self):
        with patch.dict(os.environ, {'CHELSY_SEARXNG_URL': 'http://127.0.0.1:8888'}, clear=True):
            manager = SearchManager()
            self.assertEqual(manager.provider(), 'searxng')
            with patch.object(fs, 'searxng', return_value=[]) as sx, \
                 patch.object(fs, 'news', return_value=[{'url': 'https://lenta.ru/n', 'title': 'n'}]) as news:
                items, _ = manager.search('новости', 'news')
        self.assertTrue(sx.called and news.called)
        self.assertEqual(items[0]['url'], 'https://lenta.ru/n')

    def test_public_searxng_over_plain_http_is_ignored(self):
        with patch.dict(os.environ, {'CHELSY_SEARXNG_URL': 'http://searx.example.org'}, clear=True):
            self.assertEqual(SearchManager.provider(), 'free')

    def test_nothing_found_is_reported_honestly(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(fs, 'web', return_value=[]):
            items, note = SearchManager().search('абвгд')
        self.assertEqual(items, [])
        self.assertIn('ничего подходящего', note)


if __name__ == '__main__':
    unittest.main()

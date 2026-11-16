"""SearchManager — web / news search with NO mandatory paid service.

Provider chain (first available wins):
  1. Brave Search API — only if the owner chose to set CHELSY_BRAVE_SEARCH_KEY (optional, paid);
  2. SearXNG — if CHELSY_SEARXNG_URL points to a self-hosted instance (free, whole web);
  3. free official sources (knowledge.free_sources): Wikipedia, news RSS, Hacker News,
     Stack Exchange, PyPI, GitHub — no key, no cost, always available with internet.

Keys stay on the Host. Results are untrusted data. Without internet the caller gets an explicit
note, never fabricated results.
"""
from __future__ import annotations

import os

import live_tools

from . import free_sources


def _searxng_url() -> str:
    url = os.environ.get('CHELSY_SEARXNG_URL', '').strip().rstrip('/')
    return url if url.startswith(('https://', 'http://127.0.0.1', 'http://localhost')) else ''


class SearchManager:
    def __init__(self, web=None, news=None):
        self._web = web
        self._news = news

    @staticmethod
    def configured():
        """Search is always possible: free sources need no key (internet is checked separately)."""
        return True

    @staticmethod
    def provider() -> str:
        if os.environ.get('CHELSY_BRAVE_SEARCH_KEY', '').strip():
            return 'brave'
        if _searxng_url():
            return 'searxng'
        return 'free'

    @staticmethod
    def provider_label() -> str:
        return {'brave': 'Brave Search API', 'searxng': 'SearXNG (свой поиск на хосте)',
                'free': 'бесплатные источники: Википедия, новостные RSS, Hacker News, Stack Overflow, PyPI, GitHub'}[
            SearchManager.provider()]

    def _run(self, query, kind):
        if kind == 'news' and self._news:
            return self._news(query)
        if kind != 'news' and self._web:
            return self._web(query)
        provider = self.provider()
        if provider == 'brave':
            items, note = (live_tools.brave_news if kind == 'news' else live_tools.brave_search)(query)
            if items:
                return items, note
        elif provider == 'searxng':
            items = free_sources.searxng(query, _searxng_url(), kind)
            if items:
                return items, ''
        items = free_sources.news(query) if kind == 'news' else free_sources.web(query)
        if items:
            return items, ''
        return [], ('Свежих новостей по этому запросу в новостных лентах не нашлось.' if kind == 'news'
                    else 'В бесплатных источниках (Википедия, Stack Overflow, PyPI, GitHub) ничего подходящего не нашлось.')

    def search(self, query, kind='web'):
        """Return (results, note). results: list of {url,title,excerpt,published,kind}."""
        try:
            return self._run(query, kind)
        except Exception as exc:        # network/HTTP/JSON problems
            return [], f'Поисковый сервис недоступен ({type(exc).__name__}).'

    def documentation(self, name):
        """Find official documentation pages for a product name."""
        try:
            official = free_sources.documentation(name)
        except Exception:
            official = []
        if official and self.provider() == 'free':
            return official, ''
        items, note = self.search(f'{name} official documentation', 'web')
        docs = [i for i in items if any(h in i['url'] for h in ('docs', 'documentation', 'readthedocs', 'developer', 'manual', 'tutorial'))]
        merged = official + [i for i in (docs or items) if i['url'] not in {o['url'] for o in official}]
        return merged, ('' if merged else note)

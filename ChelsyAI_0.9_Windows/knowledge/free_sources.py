"""Free, key-less sources for live answers and autonomous learning (no paid search API).

Every source here is an official, documented, free endpoint meant for programmatic use:

* Wikipedia (MediaWiki Action API, ru/en) — encyclopedic knowledge, CC BY-SA, link kept as source.
* RSS feeds of news outlets — headlines published for syndication; filtered by the question.
* Hacker News (Algolia API) — technology news.
* Stack Exchange API (Stack Overflow / ru.stackoverflow) — programming answers, 300 requests/day without a key.
* PyPI JSON API and GitHub REST API — latest versions, release dates, official homepages/docs.
* Optional SearXNG (CHELSY_SEARXNG_URL) — a free, self-hosted metasearch for the whole web.

Search engines are NOT scraped (their terms forbid it). Results are untrusted data, exactly like
results of a paid API: they go through the same fetcher (SSRF/robots), verifier and review flow.
"""
from __future__ import annotations

import html
import re
import threading
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit

import live_tools

# Wikimedia's policy asks for a descriptive agent with a way to reach the project.
USER_AGENT = 'ChelsyAI/0.9.3 (https://github.com/wotb76969-cmd/ChelsyAI; personal assistant) python-urllib'
_MAX_FEED = 1_500_000

NEWS_FEEDS = {
    'ru': ['https://lenta.ru/rss/news', 'https://ria.ru/export/rss2/archive/index.xml',
           'https://tass.ru/rss/v2.xml', 'https://www.interfax.ru/rss', 'https://habr.com/ru/rss/articles/'],
    'en': ['https://feeds.bbci.co.uk/news/world/rss.xml', 'https://feeds.bbci.co.uk/news/technology/rss.xml'],
}
_FEED_CACHE: dict[str, tuple[float, list]] = {}
_FEED_LOCK = threading.Lock()
_STOP = set('''и в во на по с со к ко о об от до за из у для что как какой какая какие это the a an of to in on for
and or is are what how why when who найди найти поищи покажи расскажи последние последний последняя свежие новости
новость news latest about про сегодня сейчас today now мне пожалуйста please такое такой такая
что-то объясни узнай скажи'''.split())


def _lang(text: str) -> str:
    return 'ru' if re.search(r'[А-Яа-яЁё]', text or '') else 'en'


def _keywords(question: str) -> list[str]:
    """Meaningful words for a search API (the API does its own morphology)."""
    words = re.findall(r'[\w\-+#]{2,}', (question or '').casefold())
    return [w for w in words if w not in _STOP]


def _stem(word: str) -> str:
    if len(word) >= 7:
        return word[:-2]
    if len(word) >= 5:
        return word[:-1]
    return word


def _terms(question: str) -> list[str]:
    """Crude stems for matching feed items locally ("Самары"/"Самаре" -> "самар")."""
    return [_stem(w) for w in _keywords(question)]


def _clean(text: str, limit: int) -> str:
    text = re.sub(r'<[^>]+>', ' ', html.unescape(str(text or '')))
    return re.sub(r'\s+', ' ', text).strip()[:limit]


def _get_json(url: str, params: dict) -> dict:
    # PyPI's JSON carries the whole release history (several MB for popular packages).
    limit = 6_000_000 if url.startswith('https://pypi.org/') else None
    return live_tools.fetch_json(url, params, headers={'User-Agent': USER_AGENT}, max_bytes=limit)


def _get_text(url: str) -> bytes:
    from urllib.request import Request
    request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/rss+xml, application/xml, text/xml'})
    with live_tools._OPENER.open(request, timeout=9) as response:
        data = response.read(_MAX_FEED + 1)
    if len(data) > _MAX_FEED:
        raise ValueError('feed too large')
    return data          # bytes: the XML declaration decides the encoding (Interfax is windows-1251)


# ------------------------------------------------------------------ Wikipedia
_WIKI_CACHE: dict[tuple, tuple[float, list]] = {}


def _polite_json(url: str, params: dict) -> dict:
    """One retry after the server's Retry-After (Wikimedia rate limits anonymous clients)."""
    from urllib.error import HTTPError
    try:
        return _get_json(url, params)
    except HTTPError as exc:
        wait = exc.headers.get('Retry-After', '') if exc.code == 429 else ''
        if not wait.isdigit() or int(wait) > 10:
            raise
        time.sleep(int(wait))
        return _get_json(url, params)


def wikipedia(question: str, lang: str | None = None, limit: int = 4) -> list[dict]:
    lang = lang or _lang(question)
    query = ' '.join(_keywords(question)) or question
    key = (lang, query.casefold(), limit)
    cached = _WIKI_CACHE.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    data = _polite_json(f'https://{lang}.wikipedia.org/w/api.php', {
        'action': 'query', 'format': 'json', 'formatversion': 2, 'utf8': 1,
        'generator': 'search', 'gsrsearch': query[:250], 'gsrlimit': limit,
        'prop': 'extracts|info', 'exintro': 1, 'explaintext': 1, 'exlimit': limit, 'exchars': 900,
        'inprop': 'url',
    })
    pages = sorted((data.get('query') or {}).get('pages') or [], key=lambda p: p.get('index', 99))
    items = []
    for page in pages:
        url = str(page.get('fullurl', ''))
        if not url.startswith('https://') or not page.get('extract'):
            continue
        items.append({'url': url, 'title': _clean(page.get('title'), 180) + ' — Википедия' * (lang == 'ru'),
                      'excerpt': _clean(page.get('extract'), 900), 'published': str(page.get('touched', ''))[:10],
                      'kind': 'web', 'source': f'{lang}.wikipedia.org'})
    if len(_WIKI_CACHE) > 500:
        _WIKI_CACHE.clear()
    _WIKI_CACHE[key] = (time.monotonic() + 3600, items)     # an hour: fewer requests, same answers
    return items


# ------------------------------------------------------------------ news (RSS + Hacker News)
def _parse_feed(text) -> list[dict]:
    root = ET.fromstring(text)
    items = []
    for node in root.iter():
        tag = node.tag.rsplit('}', 1)[-1]
        if tag not in ('item', 'entry'):
            continue
        get = lambda name: next((c for c in node if c.tag.rsplit('}', 1)[-1] == name), None)
        title = get('title')
        link = get('link')
        url = (link.get('href') if link is not None and link.get('href') else (link.text if link is not None else '')) or ''
        # Element truthiness means "has children", so pick the first one that is not None.
        date = next((e for e in (get('pubDate'), get('published'), get('updated')) if e is not None), None)
        description = next((e for e in (get('description'), get('summary')) if e is not None), None)
        published = ''
        if date is not None and date.text:
            try:
                published = parsedate_to_datetime(date.text.strip()).date().isoformat()
            except (TypeError, ValueError):
                published = date.text.strip()[:10]
        url = url.strip()
        if url.startswith('https://') and title is not None and title.text:
            items.append({'url': url[:700], 'title': _clean(title.text, 180),
                          'excerpt': _clean(description.text if description is not None else '', 600),
                          'published': published, 'kind': 'news', 'source': urlsplit(url).hostname or ''})
    return items


def _feed(url: str, ttl: float = 600) -> list[dict]:
    now = time.monotonic()
    with _FEED_LOCK:
        cached = _FEED_CACHE.get(url)
        if cached and cached[0] > now:
            return cached[1]
    try:
        items = _parse_feed(_get_text(url))
    except Exception:              # one broken feed must not hide the others
        items = []
    with _FEED_LOCK:
        _FEED_CACHE[url] = (now + ttl, items)
    return items


def news(question: str, limit: int = 8) -> list[dict]:
    lang = _lang(question)
    terms = _terms(question)
    pool = []
    for url in NEWS_FEEDS.get(lang, NEWS_FEEDS['en']):
        pool += _feed(url)
    if terms:
        scored = []
        for item in pool:
            hay = (item['title'] + ' ' + item['excerpt']).casefold()
            score = sum(1 for t in terms if re.search(r'(?<![\w])' + re.escape(t), hay))
            if score:
                scored.append((score, item['published'], item))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        picked = [i for _, _, i in scored]
    else:                          # "последние новости" without a topic: the freshest headlines
        picked = sorted(pool, key=lambda i: i['published'], reverse=True)
    tech = any(re.fullmatch(r'[a-z][\w\-+#.]*', t) for t in _keywords(question))
    if len(picked) < 3 and terms and (lang == 'en' or tech):
        try:
            picked += hacker_news(question)
        except Exception:
            pass
    seen, out = set(), []
    for item in picked:
        if item['url'] not in seen:
            seen.add(item['url'])
            out.append(item)
    return out[:limit]


def hacker_news(question: str, limit: int = 5) -> list[dict]:
    data = _get_json('https://hn.algolia.com/api/v1/search', {
        'query': ' '.join(_keywords(question))[:200] or question[:200], 'tags': 'story', 'hitsPerPage': limit})
    items = []
    for hit in data.get('hits') or []:
        url = str(hit.get('url') or '')
        if not url.startswith('https://'):
            url = f'https://news.ycombinator.com/item?id={hit.get("objectID")}'
        items.append({'url': url[:700], 'title': _clean(hit.get('title'), 180), 'excerpt': '',
                      'published': str(hit.get('created_at', ''))[:10], 'kind': 'news', 'source': 'news.ycombinator.com'})
    return items


# ------------------------------------------------------------------ programming
_CODE = re.compile(r'(python|javascript|typescript|java\b|kotlin|dart|flutter|c\+\+|c#|golang|\bgo\b|rust|sql|'
                   r'ошибк|error|exception|traceback|функци|метод|библиотек|код|code|npm|pip|git\b|docker|api)', re.I)


def stack_exchange(question: str, limit: int = 4) -> list[dict]:
    site = 'ru.stackoverflow' if _lang(question) == 'ru' else 'stackoverflow'
    data = _get_json('https://api.stackexchange.com/2.3/search/advanced', {
        'order': 'desc', 'sort': 'relevance', 'q': question[:250], 'site': site, 'pagesize': limit,
        'accepted': 'True', 'filter': 'withbody'})
    items = []
    for q in data.get('items') or []:
        url = str(q.get('link', ''))
        if url.startswith('https://'):
            stamp = time.strftime('%Y-%m-%d', time.gmtime(q.get('last_activity_date') or 0)) if q.get('last_activity_date') else ''
            items.append({'url': url, 'title': _clean(q.get('title'), 180), 'excerpt': _clean(q.get('body'), 700),
                          'published': stamp, 'kind': 'web', 'source': site + '.com'})
    return items


_VERSION = re.compile(r'(верси|релиз|release|version|обновлени|вышл[аио]?\b|changelog)', re.I)
_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_.\-]{1,40}')


def _pypi(name: str) -> str:
    """PEP 503 normalised name: PyPI redirects other spellings and redirects are not followed."""
    return re.sub(r'[-_.]+', '-', name).lower()


def releases(question: str) -> list[dict]:
    """Latest version facts from PyPI and GitHub for product names in the question."""
    items = []
    for name in dict.fromkeys(m.group(0) for m in _NAME.finditer(question or '')):
        if name.casefold() in {'the', 'and', 'latest', 'version', 'release', 'api', 'new'}:
            continue
        try:
            info = _get_json(f'https://pypi.org/pypi/{_pypi(name)}/json', {}).get('info') or {}
        except Exception:
            info = {}
        if info.get('version'):
            urls = info.get('project_urls') or {}
            page = next((u for k, u in urls.items() if k.casefold() in ('changelog', 'release notes', 'changes')), None)
            items.append({'url': (page if str(page or '').startswith('https://') else f'https://pypi.org/project/{name}/'),
                          'title': f'{info.get("name", name)} {info["version"]} — PyPI',
                          'excerpt': f'Последняя версия на PyPI: {info["version"]}. {_clean(info.get("summary"), 300)}',
                          'published': '', 'kind': 'web', 'source': 'pypi.org'})
        try:
            repos = _get_json('https://api.github.com/search/repositories',
                              {'q': f'{name} in:name', 'sort': 'stars', 'per_page': 1}).get('items') or []
        except Exception:
            repos = []
        for repo in repos[:1]:
            full = repo.get('full_name', '')
            try:
                rel = _get_json(f'https://api.github.com/repos/{full}/releases/latest', {})
            except Exception:
                rel = {}
            if rel.get('tag_name'):
                items.append({'url': str(rel.get('html_url', f'https://github.com/{full}/releases')),
                              'title': f'{full} {rel["tag_name"]} — GitHub Releases',
                              'excerpt': _clean(rel.get('body'), 600), 'published': str(rel.get('published_at', ''))[:10],
                              'kind': 'web', 'source': 'github.com'})
        if len(items) >= 4:
            break
    return items


def documentation(name: str) -> list[dict]:
    """Official homepage/docs of a project from PyPI and GitHub (for research jobs)."""
    items = []
    clean = re.sub(r'(?i)\b(official|documentation|docs|документаци\w*|официальн\w*)\b', '', name).strip()
    token = (_NAME.findall(clean) or [clean])[0]
    try:
        info = _get_json(f'https://pypi.org/pypi/{_pypi(token)}/json', {}).get('info') or {}
        for key, url in (info.get('project_urls') or {}).items():
            if str(url).startswith('https://') and any(k in key.casefold() for k in ('doc', 'home')):
                items.append({'url': url, 'title': f'{info.get("name", token)} — {key}', 'excerpt': _clean(info.get('summary'), 300),
                              'published': '', 'kind': 'web', 'source': 'pypi.org'})
    except Exception:
        pass
    try:
        for repo in (_get_json('https://api.github.com/search/repositories',
                               {'q': f'{token} in:name', 'sort': 'stars', 'per_page': 2}).get('items') or []):
            if str(repo.get('homepage') or '').startswith('https://'):
                items.append({'url': repo['homepage'], 'title': f'{repo.get("full_name")} — сайт проекта',
                              'excerpt': _clean(repo.get('description'), 300), 'published': '', 'kind': 'web',
                              'source': 'github.com'})
    except Exception:
        pass
    seen, out = set(), []
    for item in items:
        if item['url'] not in seen:
            seen.add(item['url'])
            out.append(item)
    return out


# ------------------------------------------------------------------ optional SearXNG (free, self-hosted)
def searxng(question: str, base: str, kind: str = 'web', limit: int = 6) -> list[dict]:
    data = _get_json(base.rstrip('/') + '/search', {'q': question[:300], 'format': 'json',
                                                     'categories': 'news' if kind == 'news' else 'general',
                                                     'language': 'ru' if _lang(question) == 'ru' else 'en'})
    items = []
    for r in (data.get('results') or [])[:limit]:
        url = str(r.get('url', ''))
        if url.startswith('https://'):
            items.append({'url': url[:700], 'title': _clean(r.get('title'), 180), 'excerpt': _clean(r.get('content'), 700),
                          'published': str(r.get('publishedDate') or '')[:10], 'kind': kind,
                          'source': urlsplit(url).hostname or ''})
    return items


# ------------------------------------------------------------------ combined
def web(question: str) -> list[dict]:
    """General question: encyclopedic + programming + version facts, de-duplicated."""
    results = []
    calls = [wikipedia]
    if _CODE.search(question or ''):
        calls.append(stack_exchange)
    if _VERSION.search(question or ''):
        calls.insert(0, releases)
    for call in calls:
        try:
            results += call(question)
        except Exception:        # one source down must not hide the others
            continue
    seen, out = set(), []
    for item in results:
        if item['url'] not in seen:
            seen.add(item['url'])
            out.append(item)
    return out[:8]

"""Live information adapters. No arbitrary URL fetches; bounded endpoints only."""
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_OPENER = build_opener(ProxyHandler({}), NoRedirect())
_MAX_RESPONSE = 240_000


def fetch_json(base, parameters, headers=None, max_bytes=None):
    """Read JSON from a fixed, developer-selected HTTPS endpoint."""
    limit = max_bytes or _MAX_RESPONSE
    url = base + ('?' + urlencode(parameters) if parameters else '')
    request = Request(url, headers={'User-Agent': 'ChelsyAI/0.9.3 (personal assistant)', 'Accept':'application/json', **(headers or {})})
    with _OPENER.open(request, timeout=9) as response:
        content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError('Ответ сервиса слишком большой')
        return json.loads(content.decode('utf-8'))


def is_weather(question):
    return bool(re.search(r'\b(погод[аыуеой]|температур[аыеуой]|weather|temperature|прогноз погод[ыа])\b', question, re.I))


# ------------------------------------------------------------------ weather
# Countries a user may name next to the city ("Россия, Самара", "Самара Россия").
# Stems are matched against the start of the word, so case forms work too.
_COUNTRIES = [
    ('росси', 'RU'), ('рф', 'RU'), ('russia', 'RU'), ('украин', 'UA'), ('ukrain', 'UA'), ('беларус', 'BY'),
    ('белорус', 'BY'), ('belarus', 'BY'), ('казахстан', 'KZ'), ('kazakhstan', 'KZ'), ('узбекистан', 'UZ'),
    ('кыргызстан', 'KG'), ('киргизи', 'KG'), ('таджикистан', 'TJ'), ('туркменистан', 'TM'), ('армени', 'AM'),
    ('грузи', 'GE'), ('азербайджан', 'AZ'), ('молдов', 'MD'), ('латви', 'LV'), ('литв', 'LT'), ('эстони', 'EE'),
    ('польш', 'PL'), ('финлянди', 'FI'), ('германи', 'DE'), ('germany', 'DE'), ('франци', 'FR'), ('france', 'FR'),
    ('итали', 'IT'), ('italy', 'IT'), ('испани', 'ES'), ('spain', 'ES'), ('великобритани', 'GB'), ('англи', 'GB'),
    ('сша', 'US'), ('америк', 'US'), ('usa', 'US'), ('турци', 'TR'), ('turkey', 'TR'), ('китай', 'CN'),
    ('китае', 'CN'), ('china', 'CN'), ('япони', 'JP'), ('japan', 'JP'), ('израил', 'IL'), ('оаэ', 'AE'),
    ('египет', 'EG'), ('египт', 'EG'), ('таиланд', 'TH'), ('тайланд', 'TH'), ('чехи', 'CZ'), ('сербия', 'RS'),
]
_TIME_WORDS = r'(?:сегодня|завтра|послезавтра|сейчас|утром|днём|днем|вечером|ночью|на\s+сегодня|на\s+завтра|на\s+неделю|today|tomorrow|now)'
_NOT_A_PLACE = {'общем', 'целом', 'этом', 'городе', 'моем', 'моём', 'доме', 'мире', 'мира', 'улице', 'там', 'тут',
                'здесь', 'нашем', 'моём городе', 'моем городе', 'нашем городе'}


def _country_code(word):
    w = word.casefold().strip(' .')
    for stem, code in _COUNTRIES:
        if w == stem or (w.startswith(stem) and len(w) - len(stem) <= 3):
            return code
    return None


def weather_place(question):
    """Return (place, country_code) named in a weather question, or (None, None).

    Never infers the user's location. Understands "в Самаре", "для Самары",
    "Россия, Самара", "Самара, Россия", "погода Самара", "weather in Samara".
    """
    q = re.sub(r'\s+', ' ', (question or '')).strip().rstrip(' ?!.')
    m = (re.search(r'(?:^|\s)(?:в|во|для|по)\s+(.+)$', q, re.I)
         or re.search(r'\bin\s+(.+)$', q, re.I)
         or re.search(r'(?:погод\w*|температур\w*|прогноз\w*|weather)[\s:,\-—]+(.+)$', q, re.I))
    if not m:
        return None, None
    rest = re.split(r'\s+' + _TIME_WORDS + r'\b|\?', m.group(1), maxsplit=1, flags=re.I)[0]
    rest = re.sub(r'^(?:город(?:е|а)?|г\.)\s+', '', rest.strip(), flags=re.I)
    # "в Россия, Самара" / "Россия Самара" / "Самара (Россия)"
    parts = [p.strip(' ()') for p in re.split(r'[,;/()]', rest) if p.strip(' ()')]
    country, places = None, []
    for part in parts:
        code = _country_code(part)
        if code and not country:
            country = code
            continue
        words = part.split()
        if len(words) > 1 and _country_code(words[0]) and not country:
            country, words = _country_code(words[0]), words[1:]
        elif len(words) > 1 and _country_code(words[-1]) and not country:
            country, words = _country_code(words[-1]), words[:-1]
        if words:
            places.append(' '.join(words))
    place = places[0][:60].strip() if places else None
    if not place or place.casefold() in _NOT_A_PLACE:
        return None, country
    return place, country


def weather_location(question):
    """0.9.2 compatible: the place name only."""
    return weather_place(question)[0]


def _word_forms(word, last):
    """Nominative guesses for one Russian word in a prepositional/genitive form."""
    w = word
    low = w.casefold()
    forms = [w]
    if not re.search(r'[а-яё]$', low):
        return forms
    def cut(n, add=''):
        return w[:-n] + add if n else w + add
    if last:
        if low.endswith('ле'):
            forms += [cut(1, 'ь'), cut(1, 'я')]            # Ярославле → Ярославль
        if low.endswith('ии'):
            forms += [cut(1, 'я')]                          # Евпатории → Евпатория
        elif low.endswith('и'):
            forms += [cut(1, 'ь'), cut(1, 'а'), cut(1, 'я')]  # Казани → Казань, Махачкалы…
        if low.endswith('е'):
            forms += [cut(1, 'а'), cut(1), cut(1, 'о'), cut(1, 'я'), cut(1, 'ь')]  # Самаре, Омске, Иванове
        if low.endswith('ы'):
            forms += [cut(1, 'а')]                          # для Самары → Самара
        if low.endswith('а') and len(low) > 4:
            forms += [cut(1)]                               # для Новгорода → Новгород
        if low.endswith('у'):
            forms += [cut(1, 'а'), cut(1)]
    else:  # adjectives: Нижнем Новгороде, Великом Новгороде, Старой Руссе
        if low.endswith(('ем', 'ом')):
            forms += [cut(2, 'ий'), cut(2, 'ый'), cut(2, 'ой')]
        if low.endswith(('ой', 'ей')):
            forms += [cut(2, 'ая'), cut(2, 'яя')]
        if low.endswith(('его', 'ого')):
            forms += [cut(3, 'ий'), cut(3, 'ый')]
    seen, out = set(), []
    for f in forms:
        if f and f.casefold() not in seen:
            seen.add(f.casefold())
            out.append(f)
    return out


def place_candidates(place, limit=6):
    """The place as written first, then nominative guesses ("Самаре" → "Самара")."""
    hyphen = re.match(r'^(.+?)(-на-.+)$', place)        # Ростове-на-Дону → Ростов-на-Дону
    head, tail = (hyphen.group(1), hyphen.group(2)) if hyphen else (place, '')
    words = head.split()
    if not words:
        return [place]
    out = [place]
    if len(words) == 1:
        out += [f + tail for f in _word_forms(words[0], True)]
    else:
        # Adjective + noun agree in gender: "Нижнем Новгороде" → "Нижний Новгород",
        # "Старой Руссе" → "Старая Русса".
        *adjectives, noun = words
        low = adjectives[-1].casefold()
        if low.endswith(('ем', 'ом')):
            adj_forms = [[w[:-2] + 'ий', w[:-2] + 'ый'] for w in adjectives]
            noun_forms = [noun[:-1], noun[:-1] + 'о'] if noun.casefold().endswith('е') else [noun]
        elif low.endswith(('ой', 'ей')):
            adj_forms = [[w[:-2] + 'ая', w[:-2] + 'яя'] for w in adjectives]
            noun_forms = ([noun[:-1] + 'а', noun[:-1] + 'я'] if noun.casefold().endswith(('е', 'и')) else [noun])
        elif low.endswith(('ых', 'их')):                  # Набережных Челнах → Набережные Челны
            adj_forms = [[w[:-2] + 'ые', w[:-2] + 'ие'] for w in adjectives]
            noun_forms = [noun[:-2] + 'ы', noun[:-2] + 'и'] if noun.casefold().endswith(('ах', 'ях')) else [noun]
        else:
            adj_forms = [[w] for w in adjectives]
            noun_forms = _word_forms(noun, True)[1:]
        for n in noun_forms:
            for i in range(max(len(a) for a in adj_forms)):
                out.append(' '.join([a[min(i, len(a) - 1)] for a in adj_forms] + [n]) + tail)
    seen, unique = set(), []
    for c in out:
        if c.casefold() not in seen:
            seen.add(c.casefold())
            unique.append(c)
    return unique[:limit]


def geocode(place, country=None):
    """Best match for a place name; tries nominative forms of Russian case endings."""
    fallback = None
    candidates = place_candidates(place)
    names = {c.casefold() for c in candidates}
    for candidate in candidates:
        params = {'name': candidate, 'count': 10, 'language': 'ru', 'format': 'json'}
        if country:
            params['countryCode'] = country
        results = fetch_json('https://geocoding-api.open-meteo.com/v1/search', params).get('results') or []
        exact = [r for r in results if str(r.get('name', '')).casefold() in names]
        if exact:
            return max(exact, key=lambda r: r.get('population') or 0)
        if results and fallback is None and candidate != place:
            fallback = results[0]
    return fallback


def weather(question):
    place, country = weather_place(question)
    if not place:
        return ('Уточни город, пожалуйста. Например: «Какая погода в Москве?» или «Погода: Самара, Россия» — '
                'я не определяю твоё местоположение автоматически.'), []
    item = geocode(place, country)
    if not item:
        return (f'Не нашла город «{place}». Напиши название в именительном падеже, при желании со страной — '
                'например: «Погода: Самара, Россия».'), []
    forecast = fetch_json('https://api.open-meteo.com/v1/forecast', {
        'latitude': item['latitude'], 'longitude': item['longitude'],
        'current': 'temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m',
        'timezone': 'auto', 'forecast_days': 1,
    })
    current = forecast.get('current') or {}
    if current.get('temperature_2m') is None:
        return 'Погодный сервис не вернул температуру. Попробуй чуть позже.', []
    code = current.get('weather_code')
    descriptions = {0:'ясно',1:'преимущественно ясно',2:'переменная облачность',3:'пасмурно',45:'туман',48:'изморозь',51:'слабая морось',53:'морось',55:'сильная морось',56:'ледяная морось',57:'сильная ледяная морось',61:'небольшой дождь',63:'дождь',65:'сильный дождь',66:'ледяной дождь',67:'сильный ледяной дождь',71:'небольшой снег',73:'снег',75:'сильный снег',77:'снежная крупа',80:'ливневый дождь',81:'ливень',82:'сильный ливень',85:'снегопад',86:'сильный снегопад',95:'гроза',96:'гроза с градом',99:'сильная гроза с градом'}
    name = item.get('name', place)
    region = item.get('admin1', '')
    country_name = item.get('country', '')
    where = ', '.join(x for x in (name, region if region and region != name else '', country_name) if x)
    stamp = str(current.get('time', 'время неизвестно')).replace('T', ' ')
    result = f'**{where}** — сейчас **{current["temperature_2m"]} °C**, {descriptions.get(code, "условия уточняются")}.\n\n'
    result += f'Ощущается как {current.get("apparent_temperature","?")} °C; влажность {current.get("relative_humidity_2m","?")}%, ветер {current.get("wind_speed_10m","?")} км/ч.\n'
    result += f'\nДанные на {stamp} (местное время города). Источник: [Open-Meteo](https://open-meteo.com/).'
    return result, [{'url':'https://open-meteo.com/', 'title':'Open-Meteo', 'excerpt': str(current), 'kind':'weather'}]


def is_weather_followup(previous_answer, question):
    """True when Chelsy just asked which city and the user replies with a place only."""
    prev = (previous_answer or '').strip()
    if not prev.startswith(('Уточни город', 'Не нашла город', 'Не удалось найти город')):
        return False
    q = (question or '').strip()
    return 0 < len(q) <= 60 and len(q.split()) <= 6 and not q.endswith('?')


_RESEARCH = re.compile(
    r'^(?:пожалуйста[,\s]+)?(?:изучи|исследуй|проштудируй|проиндексируй|прочитай\s+и\s+запомни)\b'
    r'|^(?:please\s+)?(?:study|research|index|learn\s+from)\s+(?:the\s+)?(?:docs|documentation|site|website|page|source|https?://)', re.I)
_NEWS = re.compile(r'(?:новост|что\s+(?:произошло|случилось|нового)|последние\s+событи|headlines|\bnews\b|what\s+happened)', re.I)
_WEB = re.compile(
    r'(?:найди|поищи|проверь\s+в\s+(?:интернете|сети)|загугли|поиск\s+в\s+интернете|в\s+интернете|в\s+сети|'
    r'последн(?:ий|яя|ее|ие|юю)\s+(?:верси|релиз|курс)|свеж(?:ие|ая|ий)|сегодня|сейчас|на\s+данный\s+момент|актуальн|'
    r'курс\s+(?:доллара|евро|рубля|биткоин)|сколько\s+стоит|цена\s+на|в\s+20[2-9]\d\s+году|'
    r'latest|recent|current(?:ly)?\b|search\s+online|look\s+up|today|right\s+now|price\s+of)', re.I)
_SMALLTALK = re.compile(
    r'^(?:привет\w*|здравствуй\w*|добр(?:ое|ый)\s+\w+|хай|ку|как\s+(?:дела|ты|жизнь|настроение)\w*|что\s+делаешь|спасибо\w*|'
    r'пока|hi|hello|hey|how\s+are\s+you|thanks?|thank\s+you|good\s+(?:morning|evening|night))\b', re.I)
URL_IN_TEXT = re.compile(r'https?://[^\s<>"\'«»]+', re.I)


def route(question, web_enabled=True):
    """Classify a request: chat | local | weather | news | web | research.

    The route only says what the request NEEDS. Whether a search actually
    happens is decided (and honestly reported) by the intelligence engine.
    """
    q = re.sub(r'\s+', ' ', (question or '')).strip()
    low = q.casefold()
    if is_weather(low):
        return 'weather'
    if _RESEARCH.search(low):
        return 'research'
    if _NEWS.search(low):
        return 'news'
    if _SMALLTALK.search(low) and len(q) < 60:
        return 'chat'
    if _WEB.search(low):
        return 'web'
    return 'local'


def search_intent(question):
    """0.9.2 compatible view of route(): 'weather', 'web' or None."""
    kind = route(question)
    if kind == 'weather':
        return 'weather'
    if kind in ('web', 'news'):
        return 'web'
    return None


_NET = {'value': None, 'stamp': 0.0}


def internet_available(ttl=30.0):
    """Cheap connectivity probe (TCP to the search/weather APIs). Cached."""
    import socket
    import time
    if os.environ.get('CHELSY_OFFLINE') == '1':
        return False
    now = time.monotonic()
    if _NET['value'] is not None and now - _NET['stamp'] < ttl:
        return _NET['value']
    ok = False
    for host in ('api.search.brave.com', 'api.open-meteo.com'):
        try:
            with socket.create_connection((host, 443), timeout=2.5):
                ok = True
                break
        except OSError:
            continue
    _NET['value'], _NET['stamp'] = ok, now
    return ok


def brave_news(question):
    """Fresh news with publication dates via Brave News Search API."""
    key = os.environ.get('CHELSY_BRAVE_SEARCH_KEY', '').strip()
    if not key:
        return [], ('Для поиска свежих новостей нужен ключ Brave Search API. На ноутбуке-хосте '
                    'задай CHELSY_BRAVE_SEARCH_KEY; клиентам ключ не передаётся.')
    freshness = 'pd' if re.search(r'(сегодня|today|сейчас|now)', question, re.I) else 'pw'
    response = fetch_json('https://api.search.brave.com/res/v1/news/search', {
        'q': question[:400], 'count': 8, 'safesearch': 'moderate', 'freshness': freshness,
    }, headers={'X-Subscription-Token': key})
    items = []
    for result in (response.get('results') or [])[:8]:
        url = str(result.get('url', ''))
        if not url.startswith('https://'):
            continue
        items.append({'url': url[:700], 'title': str(result.get('title', ''))[:180],
                      'excerpt': re.sub('<[^>]+>', '', str(result.get('description', '')))[:600],
                      'published': str(result.get('page_age') or result.get('age') or '')[:40],
                      'source': str((result.get('meta_url') or {}).get('hostname', ''))[:120],
                      'kind': 'news'})
    return items, '' if items else 'Поиск новостей не вернул результатов.'


def brave_search(question):
    key = os.environ.get('CHELSY_BRAVE_SEARCH_KEY', '').strip()
    if not key:
        return [], 'Для актуального поиска по всему интернету нужен ключ Brave Search API. На ноутбуке задай CHELSY_BRAVE_SEARCH_KEY; ключ не нужно передавать клиентам.'
    response = fetch_json('https://api.search.brave.com/res/v1/web/search', {
        'q': question[:500], 'count': 5, 'safesearch':'moderate'
    }, headers={'X-Subscription-Token':key})
    items=[]
    for result in (response.get('web') or {}).get('results',[])[:5]:
        url = str(result.get('url',''))
        if not url.startswith('https://'): continue
        items.append({'url':url[:700], 'title':str(result.get('title',''))[:180], 'excerpt':re.sub('<[^>]+>','',str(result.get('description','')))[:850],
                      'published': str(result.get('page_age') or result.get('age') or '')[:40], 'kind':'web'})
    return items, '' if items else 'Поиск не вернул подходящих результатов.'


def chat_greeting(question):
    q = re.sub(r'[!?.,\s]+', ' ', question.casefold()).strip()
    greetings = {'привет':'Привет! 💜 Чем помочь?', 'здравствуй':'Привет! 💜 Чем помочь?', 'здравствуйте':'Здравствуйте! Чем могу помочь?', 'как дела':'Всё в порядке, спасибо! 💜 Я готова помочь с вопросами, кодом или поиском информации. А как у тебя дела?', 'как ты':'Всё хорошо! 💜 Готова помочь. Что обсудим?', 'hello':'Hello! 💜 How can I help?', 'hi':'Hi! 💜 What can I help you with?', 'how are you':'I am ready to help! 💜 How are you doing?'}
    return greetings.get(q)

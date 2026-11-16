"""Small, dependency-free quality checks; no arbitrary web access."""
import re

_RUSSIAN = re.compile(r'[А-Яа-яЁё]')
_LATIN_WORD = re.compile(r'(?<![\w])(?:[A-Za-z]{3,})(?![\w])')
_TECH_WORDS = {
    'api', 'python', 'javascript', 'typescript', 'html', 'css', 'json', 'sql', 'sqlite',
    'supabase', 'ollama', 'flutter', 'android', 'windows', 'linux', 'github', 'http',
    'https', 'url', 'open', 'meteo', 'brave', 'search', 'chelsy', 'chatgpt', 'fastapi',
    'docker', 'git', 'npm', 'pip', 'exe', 'apk', 'web', 'client', 'host', 'token',
}


def requested_language(question):
    """Detect dominant script for a Russian/English exchange (best effort)."""
    cyr = len(_RUSSIAN.findall(question))
    lat = len(re.findall(r'[A-Za-z]', question))
    return 'ru' if cyr > lat and cyr >= 3 else 'en' if lat >= 3 and lat > cyr else None


_ENGLISH_FUNCTION = {
    'the', 'and', 'but', 'or', 'of', 'to', 'in', 'on', 'for', 'with', 'from', 'by', 'at', 'as', 'is', 'are', 'was',
    'were', 'be', 'been', 'this', 'that', 'these', 'those', 'it', 'its', 'you', 'your', 'we', 'they', 'can', 'will',
    'would', 'should', 'could', 'not', 'have', 'has', 'had', 'which', 'what', 'when', 'where', 'why', 'how', 'also',
    'however', 'because', 'so', 'if', 'then', 'than', 'there', 'here', 'about', 'into', 'more', 'most', 'some', 'such',
    'just', 'very', 'like', 'let', "let's", 'example', 'note', 'step', 'first', 'second', 'finally', 'well',
}
_LINK_TEXT = re.compile(r'\[[^\]]*\]\([^)]*\)')
_LATIN_TOKEN = re.compile(r"(?<![\w-])[A-Za-z][A-Za-z']*(?![\w-])")


def is_mixed_russian_answer(question, response):
    """Find stray English prose in a Russian answer.

    Ignored: code, URLs, Markdown link texts (source titles), product names (capitalised
    words that are not English function words) and known technical terms.
    Flagged: two or more lowercase English words, any English function word used as prose,
    or a run of three Latin words in a row.
    """
    if requested_language(question) != 'ru':
        return False
    cleaned = _LINK_TEXT.sub(' ', response or '')
    cleaned = re.sub(r'```.*?```|`[^`]*`|https?://\S+', ' ', cleaned, flags=re.S | re.I)
    tokens = _LATIN_TOKEN.findall(cleaned)
    prose = []
    for token in tokens:
        low = token.casefold()
        if low in _TECH_WORDS:
            continue
        if low in _ENGLISH_FUNCTION or (token[0].islower() and len(token) >= 3):
            prose.append(low)
    if len(prose) >= 2 or any(w in _ENGLISH_FUNCTION and len(w) > 3 for w in prose):
        return True
    # "Brave Search API" is fine; "Light Scatters More" style English sentences are not.
    runs = re.findall(r"(?:[A-Za-z][A-Za-z']+[ ,]+){3,}[A-Za-z][A-Za-z']+", cleaned)
    return any(sum(w.casefold() not in _TECH_WORDS for w in re.findall(r"[A-Za-z']+", r)) >= 3 for r in runs)


def capability_answer(question, online_search_enabled=False):
    """Honest answers about learning vs browsing; avoid small-model hallucination."""
    q = question.casefold().strip()
    if not re.search(r'(?:самостоятельн|самообуч|самообучен|обучаешь|обучает|изучаешь|изучает|учишься|learn|self.learn)', q):
        return None
    if not re.search(r'(?:интернет|сет[ьи]|сайт|источник|ресурс|знани|данны|information|internet|web|самообуч)', q):
        return None
    if requested_language(question) == 'en':
        return ('I do not retrain my model automatically. I search free open sources (Wikipedia, news feeds, '
                'Stack Overflow, PyPI, GitHub) and save reliable material in my knowledge base. '
                'That is not the same as training my model weights.')
    search = ('Но я сама ищу актуальную информацию в открытых источниках — Википедии, новостных лентах, '
              'Stack Overflow, PyPI и GitHub — без платных сервисов, и сохраняю надёжные материалы '
              'в свою базу знаний, чтобы использовать их в следующих ответах.'
              if online_search_enabled else
              'Сейчас поиск в интернете недоступен, поэтому отвечаю по базе знаний, которую уже собрала, '
              'и по своим знаниям.')
    return ('Нет, я не переобучаю свою языковую модель самостоятельно. ' + search +
            ' Это поиск и пополнение базы знаний, а не изменение весов модели.')


# ---------------------------------------------------------------- 0.9.3 checks
from dataclasses import dataclass, field

_CODE_OR_URL = re.compile(r'```.*?```|`[^`]*`|https?://\S+|\[[^\]]*\]\([^)]*\)', re.S | re.I)
_CJK = re.compile(r'[぀-ヿ㐀-䶿一-鿿가-힯]')
_WORD = re.compile(r'[^\W\d_]{2,}', re.UNICODE)
_FALSE_SEARCH = re.compile(
    r'(?:я\s+(?:только\s+что\s+)?(?:поискал[аи]?|нашл[аи]|проверил[аи]|загуглил[аи])\s+(?:в\s+)?(?:интернете|сети|google|гугле)'
    r'|по\s+данным\s+(?:моего|последнего)\s+поиска'
    r'|i\s+(?:just\s+)?(?:searched|googled|looked\s+(?:it\s+)?up|browsed)\s+(?:the\s+)?(?:web|internet|online)'
    r'|according\s+to\s+my\s+(?:web\s+)?search)', re.I)


def detect_language(text):
    """'ru', 'en' or None for an answer (code, links and identifiers ignored)."""
    cleaned = _CODE_OR_URL.sub(' ', text or '')
    cyr = len(_RUSSIAN.findall(cleaned))
    lat = len(re.findall(r'[A-Za-z]', cleaned))
    total = cyr + lat
    if total < 12:
        return None
    if cyr / total >= 0.55:
        return 'ru'
    if lat / total >= 0.8:
        return 'en'
    return None


def complexity(question):
    """Rough answer-length budget for the question: 'short' | 'medium' | 'long'."""
    q = (question or '').strip()
    words = len(_WORD.findall(q))
    low = q.casefold()
    if re.search(r'(подробн|пошагов|сравни|план|напиши (код|программ|скрипт|статью|эссе)|explain in detail|step by step|compare|write (a|the) (code|program|script|essay))', low):
        return 'long'
    if words <= 6 and not re.search(r'(почему|как работает|объясни|что такое|why|how does|explain|what is)', low):
        return 'short'
    return 'medium'


def repetition_ratio(text):
    """Share of repeated word 4-grams (0 = none, close to 1 = loops)."""
    words = [w.casefold() for w in _WORD.findall(_CODE_OR_URL.sub(' ', text or ''))]
    if len(words) < 24:
        return 0.0
    grams = [' '.join(words[i:i + 4]) for i in range(len(words) - 3)]
    return 1.0 - len(set(grams)) / len(grams)


@dataclass
class Assessment:
    issues: list = field(default_factory=list)
    serious: bool = False
    language: str | None = None

    def add(self, issue, serious=False):
        self.issues.append(issue)
        self.serious = self.serious or serious


def assess(question, answer, expected_language=None, searched=False):
    """Detect obviously broken answers that justify one controlled regeneration."""
    result = Assessment()
    text = (answer or '').strip()
    expected = expected_language or requested_language(question)
    result.language = detect_language(text)
    if not text:
        result.add('empty', True)
        return result
    plain = _CODE_OR_URL.sub(' ', text)
    if not _CJK.search(question or '') and len(_CJK.findall(plain)) >= 3:
        result.add('foreign-script', True)
    if expected and result.language and result.language != expected:
        result.add('wrong-language', True)
    if expected == 'ru' and is_mixed_russian_answer(question, text):
        result.add('mixed-language', True)
    ratio = repetition_ratio(text)
    if ratio > 0.45:
        result.add('repetition', True)
    elif ratio > 0.25:
        result.add('some-repetition')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 6 and len(set(lines)) <= len(lines) / 2:
        result.add('repeated-lines', True)
    letters = sum(ch.isalpha() for ch in plain)
    if len(plain) > 40 and letters / max(1, len(plain)) < 0.35 and '```' not in text:
        result.add('gibberish', True)
    if re.search(r'\S{90,}', plain):
        result.add('unbroken-token-run', True)
    if not searched and _FALSE_SEARCH.search(text):
        result.add('false-search-claim', True)
    return result


def remove_false_search_claims(text):
    """Last-resort cleanup when the model still claims an online search it never did."""
    return _FALSE_SEARCH.sub('по моим знаниям', text or '')

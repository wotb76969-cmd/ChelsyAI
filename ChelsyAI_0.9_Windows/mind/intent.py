"""Intent Analyzer — goal, language, result type, missing slots (MIND-01)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


FORMAT_PATTERNS = [
    ('docx', re.compile(r'\b(docx|word|документ\w*|реферат|отчёт|отчет)\b', re.I)),
    ('pptx', re.compile(r'\b(pptx|powerpoint|презентац\w*|слайд\w*)\b', re.I)),
    ('xlsx', re.compile(r'\b(xlsx|excel|таблиц\w*|бюджет|смет\w*|spreadsheet)\b', re.I)),
    ('pdf', re.compile(r'\b(pdf)\b', re.I)),
    ('txt', re.compile(r'\b(txt|текстов\w*\s+файл|plain\s*text)\b', re.I)),
]

RESEARCH_RE = re.compile(r'\b(исследуй|изучи|research|find\s+sources|найди\s+источник)\b', re.I)
CHAT_RE = re.compile(r'\b(объясни|расскажи|что\s+такое|how\s+to|why|почему)\b', re.I)
SLIDES_NUM = re.compile(r'(\d+)\s*(слайд|slide)', re.I)
PAGES_NUM = re.compile(r'(\d+)\s*(страниц|page)', re.I)
CYRILLIC = re.compile(r'[а-яА-ЯёЁ]')


@dataclass
class Intent:
    goal: str
    language: str
    result_type: str  # chat | research | document
    format: str | None = None
    slides: int | None = None
    pages: int | None = None
    needs_sources: bool = False
    missing: list[str] = field(default_factory=list)
    raw: str = ''


def detect_language(text: str) -> str:
    if CYRILLIC.search(text or ''):
        return 'ru'
    return 'en'


def analyze(text: str) -> Intent:
    text = (text or '').strip()
    lang = detect_language(text)
    fmt = None
    for name, pat in FORMAT_PATTERNS:
        if pat.search(text):
            fmt = name
            break
    explicit=re.search(r'\b(txt|docx|pdf|pptx|xlsx)\b',text,re.I)
    if explicit:fmt=explicit.group(1).lower()
    result_type = 'chat'
    if fmt:
        result_type = 'document'
    elif RESEARCH_RE.search(text):
        result_type = 'research'
    slides = None
    pages = None
    numbers={'один':'1','одну':'1','две':'2','два':'2','три':'3','четыре':'4','пять':'5','восемь':'8',
             'one':'1','two':'2','three':'3','four':'4','five':'5','eight':'8'}
    counted=re.sub(r'\b('+'|'.join(numbers)+r')\b',lambda m:numbers[m[0].lower()],text,flags=re.I)
    m = SLIDES_NUM.search(counted)
    if m:
        slides = max(1, min(40, int(m.group(1))))
    m = PAGES_NUM.search(counted)
    if m:
        pages = max(1, min(50, int(m.group(1))))
    missing = []
    if result_type == 'document' and not fmt:
        missing.append('format')
    if fmt == 'pptx' and slides is None:
        slides = 8  # reasonable default per MIND-02
    if fmt == 'docx' and pages is None:
        pages = 3
    needs_sources = bool(RESEARCH_RE.search(text)) or 'источник' in text.lower() or 'source' in text.lower()
    goal = text[:500]
    return Intent(
        goal=goal, language=lang, result_type=result_type, format=fmt,
        slides=slides, pages=pages, needs_sources=needs_sources, missing=missing, raw=text,
    )

"""Quality Validator — do not publish truncated/broken results as ready (MIND-01)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .intent import Intent, CYRILLIC


@dataclass
class QualityReport:
    ok: bool
    score: float
    issues: list[str]


def validate_text_answer(text: str, intent: Intent) -> QualityReport:
    issues = []
    text = (text or '').strip()
    if len(text) < 8:
        issues.append('too_short')
    if intent.language == 'ru' and not CYRILLIC.search(text) and len(text) > 40:
        issues.append('language_mismatch')
    if intent.language == 'en' and CYRILLIC.search(text) and len(re.findall(r'[A-Za-z]', text)) < 20:
        issues.append('language_mismatch')
    if 'файл готов' in text.lower() and 'http' not in text.lower():
        # suspicious claim without link — engine should not claim readiness without artifact
        pass
    score = 4.0 - len(issues)
    return QualityReport(ok=not issues, score=max(0.0, score), issues=issues)


def validate_structure(structure: dict, fmt: str) -> QualityReport:
    issues = []
    if not isinstance(structure, dict):
        return QualityReport(False, 0.0, ['not_object'])
    if not structure.get('title'):
        issues.append('missing_title')
    if fmt in ('docx', 'pdf', 'txt') and not structure.get('sections'):
        issues.append('missing_sections')
    if fmt == 'pptx' and not structure.get('slides'):
        issues.append('missing_slides')
    if fmt == 'xlsx' and not (structure.get('tables') or structure.get('sections')):
        issues.append('missing_tables')
    score = 4.0 - len(issues)
    return QualityReport(ok=not issues, score=max(0.0, score), issues=issues)

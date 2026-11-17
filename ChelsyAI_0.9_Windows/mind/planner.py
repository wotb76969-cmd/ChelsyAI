"""Planner — short user-visible stages, not chain-of-thought dump (MIND-01)."""
from __future__ import annotations

from dataclasses import dataclass

from .intent import Intent
from .router import RouterDecision


@dataclass
class Plan:
    stages: list[str]
    route: str
    format: str | None
    params: dict


def build_plan(intent: Intent, decision: RouterDecision) -> Plan:
    route = decision.route
    if route == 'chat':
        stages = ['Понимаю вопрос', 'Готовлю ответ', 'Проверяю качество']
    elif route == 'research':
        stages = ['Формирую запрос', 'Ищу источники', 'Проверяю материалы', 'Готовлю отчёт']
    else:
        stages = [
            'Определяю формат',
            'Строю структуру',
            'Генерирую содержимое',
            'Собираю файл',
            'Проверяю результат',
        ]
    params = {
        'language': intent.language,
        'format': intent.format or (route if route in ('docx', 'pptx', 'xlsx', 'pdf', 'txt') else None),
        'slides': intent.slides,
        'pages': intent.pages,
        'needs_sources': intent.needs_sources,
        'goal': intent.goal,
    }
    return Plan(stages=stages, route=route, format=params['format'], params=params)

"""Trainable Task Router — real weights, not a renamed prompt (MIND-01 / MIND-03)."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from .intent import analyze

ROUTES = ('chat', 'research', 'docx', 'pptx', 'xlsx', 'pdf', 'txt')


def _tokenize(text: str) -> list[str]:
    text = (text or '').lower()
    text = re.sub(r'[^\w\sа-яё-]', ' ', text, flags=re.I)
    return [t for t in text.split() if len(t) > 1]


@dataclass
class RouterDecision:
    route: str
    confidence: float
    scores: dict
    intent_hint: str


class TaskRouter:
    """Bag-of-words + learned weights (logistic / softmax over route scores).

    Weights file schema::
        {"version": 1, "routes": [...], "bias": {...}, "weights": {route: {token: float}},
         "seed": 42, "metrics": {...}, "dataset_sha256": "..."}
    """

    def __init__(self, weights: dict | None = None):
        self.weights = weights or self._heuristic_weights()

    @staticmethod
    def _heuristic_weights() -> dict:
        """Bootstrap weights before first training run — still explicit, versioned."""
        seed = {
            'chat': {'объясни': 1.2, 'расскажи': 1.0, 'what': 0.8, 'how': 0.7, 'почему': 0.9},
            'research': {'исследуй': 2.0, 'изучи': 1.8, 'research': 2.0, 'источник': 1.2},
            'docx': {'docx': 2.5, 'word': 1.5, 'документ': 1.8, 'реферат': 2.0, 'отчёт': 1.6, 'отчет': 1.6},
            'pptx': {'pptx': 2.5, 'презентац': 2.2, 'слайд': 2.0, 'powerpoint': 2.0},
            'xlsx': {'xlsx': 2.5, 'excel': 2.0, 'таблиц': 1.8, 'бюджет': 2.0, 'смет': 1.7},
            'pdf': {'pdf': 2.5},
            'txt': {'txt': 2.0, 'текстовый': 1.5},
        }
        # expand prefix keys into exact tokens used at score time via startswith match
        return {
            'version': 1,
            'routes': list(ROUTES),
            'bias': {r: 0.0 for r in ROUTES},
            'weights': seed,
            'seed': 0,
            'metrics': {'note': 'heuristic-bootstrap'},
            'dataset_sha256': '',
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.weights, ensure_ascii=False, indent=2), encoding='utf-8')

    @classmethod
    def load(cls, path: Path) -> 'TaskRouter':
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls(data)

    def score(self, text: str) -> dict[str, float]:
        tokens = _tokenize(text)
        intent = analyze(text)
        scores = {r: float(self.weights.get('bias', {}).get(r, 0.0)) for r in ROUTES}
        wmap = self.weights.get('weights', {})
        for route in ROUTES:
            rw = wmap.get(route, {})
            for tok in tokens:
                if tok in rw:
                    scores[route] += float(rw[tok])
                else:
                    for key, val in rw.items():
                        if tok.startswith(key) or key.startswith(tok):
                            scores[route] += float(val) * 0.6
                            break
            if intent.format == route:
                scores[route] += 3.0
            if intent.result_type == 'research' and route == 'research':
                scores[route] += 2.0
            if intent.result_type == 'chat' and route == 'chat':
                scores[route] += 0.5
        return scores

    def route(self, text: str) -> RouterDecision:
        scores = self.score(text)
        # softmax confidence
        mx = max(scores.values())
        exps = {k: math.exp(v - mx) for k, v in scores.items()}
        total = sum(exps.values()) or 1.0
        probs = {k: exps[k] / total for k in scores}
        best = max(probs, key=probs.get)
        intent = analyze(text)
        return RouterDecision(
            route=best, confidence=float(probs[best]), scores=probs,
            intent_hint=intent.result_type,
        )


def load_default_router() -> TaskRouter:
    base = Path(__file__).resolve().parent.parent / 'training' / 'datasets' / 'router_weights_v1.json'
    if base.is_file():
        try:
            return TaskRouter.load(base)
        except (OSError, ValueError, KeyError):
            pass
    return TaskRouter()

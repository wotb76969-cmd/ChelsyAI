"""Train Task Router weights from JSONL dataset (MIND-03).

Does NOT use private user chats. Writes weights + metrics + hashes.
Usage:
  python -m training.router_train
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mind.router import ROUTES, TaskRouter, _tokenize

DATA = Path(__file__).resolve().parent / 'datasets'
SEED = 42


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def train(epochs: int = 8, lr: float = 0.35) -> dict:
    random.seed(SEED)
    train_rows = load_jsonl(DATA / 'router_train_v1.jsonl')
    val_rows = load_jsonl(DATA / 'router_val_v1.jsonl')
    test_rows = load_jsonl(DATA / 'router_test_v1.jsonl')
    bias = {r: 0.0 for r in ROUTES}
    weights = {r: defaultdict(float) for r in ROUTES}

    def scores(text):
        tokens = _tokenize(text)
        sc = {r: bias[r] for r in ROUTES}
        for r in ROUTES:
            for t in tokens:
                sc[r] += weights[r][t]
        return sc

    def predict(text):
        sc = scores(text)
        mx = max(sc.values())
        ex = {k: math.exp(v - mx) for k, v in sc.items()}
        z = sum(ex.values()) or 1.0
        probs = {k: ex[k] / z for k in ROUTES}
        return max(probs, key=probs.get), probs

    def accuracy(rows):
        ok = sum(1 for row in rows if predict(row['text'])[0] == row['route'])
        return ok / max(1, len(rows))

    for _ in range(epochs):
        random.shuffle(train_rows)
        for row in train_rows:
            pred, probs = predict(row['text'])
            tokens = _tokenize(row['text'])
            target = row['route']
            for r in ROUTES:
                grad = probs[r] - (1.0 if r == target else 0.0)
                bias[r] -= lr * grad
                for t in tokens:
                    weights[r][t] -= lr * grad

    payload = {
        'version': 1,
        'routes': list(ROUTES),
        'bias': bias,
        'weights': {r: dict(weights[r]) for r in ROUTES},
        'seed': SEED,
        'metrics': {
            'train_acc': round(accuracy(train_rows), 4),
            'val_acc': round(accuracy(val_rows), 4),
            'test_acc': round(accuracy(test_rows), 4),
            'epochs': epochs,
            'lr': lr,
        },
        'dataset_sha256': {
            'train': file_sha(DATA / 'router_train_v1.jsonl'),
            'val': file_sha(DATA / 'router_val_v1.jsonl'),
            'test': file_sha(DATA / 'router_test_v1.jsonl'),
        },
    }
    out = DATA / 'router_weights_v1.json'
    TaskRouter(payload).save(out)
    (DATA / 'router_train_report.json').write_text(
        json.dumps(payload['metrics'] | {'weights_path': out.name, 'weights_sha256': file_sha(out)},
                   ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return payload


def main():
    result = train()
    print(json.dumps(result['metrics'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

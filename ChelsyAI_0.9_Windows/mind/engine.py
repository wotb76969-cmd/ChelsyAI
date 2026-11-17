"""Chelsy Mind Engine — wires intent → router → plan → model/artifacts → validate."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .intent import analyze
from .planner import build_plan
from .policy import check_tool, assert_owner
from .quality import validate_text_answer, validate_structure
from .router import load_default_router, TaskRouter
from .artifacts.builder import ArtifactSpec, build_artifact


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MindResult:
    route: str
    stages: list[str]
    answer: str = ''
    artifact_id: str | None = None
    task_id: str | None = None
    meta: dict = field(default_factory=dict)


class MindEngine:
    def __init__(self, conn: sqlite3.Connection, artifacts_root: Path, router: TaskRouter | None = None):
        self.conn = conn
        self.artifacts_root = Path(artifacts_root)
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.router = router or load_default_router()

    def _log_route(self, user_id: str, intent_type: str, route: str, confidence: float) -> None:
        self.conn.execute(
            'INSERT INTO mind_router_log(created, user_id, intent, route, confidence, model, accepted) '
            'VALUES (?,?,?,?,?,?,1)',
            (_now(), user_id, intent_type, route, confidence, 'task-router-v1'),
        )

    def create_task(self, user_id: str, kind: str, params: dict, *,
                    idempotency_key: str = '') -> str:
        if idempotency_key:
            row = self.conn.execute(
                'SELECT id, status FROM mind_tasks WHERE user_id=? AND idempotency_key=?',
                (user_id, idempotency_key),
            ).fetchone()
            if row:
                return row[0]
        pending = self.conn.execute(
            "SELECT COUNT(*) FROM mind_tasks WHERE user_id=? AND status IN ('queued','running')",
            (user_id,),
        ).fetchone()[0]
        if pending >= 2:
            raise RuntimeError('Слишком много незавершённых задач')
        queued = self.conn.execute(
            "SELECT COUNT(*) FROM mind_tasks WHERE status IN ('queued','running')"
        ).fetchone()[0]
        if queued >= 20:
            raise RuntimeError('Очередь переполнена')
        task_id = str(uuid.uuid4())
        self.conn.execute(
            '''INSERT INTO mind_tasks(id, user_id, kind, status, created, updated, params_json, idempotency_key)
               VALUES (?,?,?,?,?,?,?,?)''',
            (task_id, user_id, kind, 'queued', _now(), _now(),
             json.dumps(params, ensure_ascii=False), idempotency_key or ''),
        )
        return task_id

    def cancel_task(self, user_id: str, task_id: str) -> None:
        row = self.conn.execute(
            'SELECT user_id, status FROM mind_tasks WHERE id=?', (task_id,)
        ).fetchone()
        if not row:
            raise LookupError('Задача не найдена')
        assert_owner(row[0], user_id)
        self.conn.execute(
            'UPDATE mind_tasks SET cancel_requested=1, updated=? WHERE id=?',
            (_now(), task_id),
        )
        if row[1] in ('queued',):
            self.conn.execute(
                "UPDATE mind_tasks SET status='cancelled', updated=? WHERE id=?",
                (_now(), task_id),
            )

    def handle(self, user_id: str, text: str, *, idempotency_key: str = '',
               generate_text=None) -> MindResult:
        intent = analyze(text)
        decision = self.router.route(text)
        plan = build_plan(intent, decision)
        self._log_route(user_id, intent.result_type, decision.route, decision.confidence)

        if decision.route == 'chat' or (decision.route == 'research' and not intent.format):
            tool = check_tool('chat_generate' if decision.route == 'chat' else 'research_search')
            if not tool.allowed:
                raise PermissionError(tool.reason)
            answer = ''
            if generate_text:
                answer = generate_text(text, plan) or ''
            else:
                answer = self._fallback_answer(intent, plan)
            report = validate_text_answer(answer, intent)
            if not report.ok and generate_text:
                answer = generate_text(text + '\n\n[исправь: ' + ','.join(report.issues) + ']', plan) or answer
            return MindResult(route=decision.route, stages=plan.stages, answer=answer,
                              meta={'confidence': decision.confidence, 'quality': report.issues})

        # Document routes
        fmt = decision.route if decision.route in ('docx', 'pptx', 'xlsx', 'pdf', 'txt') else (intent.format or 'docx')
        tool = check_tool(f'artifact_build_{fmt}', params=plan.params)
        if not tool.allowed:
            raise PermissionError(tool.reason)
        task_id = self.create_task(user_id, f'artifact:{fmt}', plan.params, idempotency_key=idempotency_key)
        self.conn.execute(
            "UPDATE mind_tasks SET status='running', progress=0.1, updated=? WHERE id=?",
            (_now(), task_id),
        )
        # Check cancel
        if self.conn.execute('SELECT cancel_requested FROM mind_tasks WHERE id=?', (task_id,)).fetchone()[0]:
            self.conn.execute(
                "UPDATE mind_tasks SET status='cancelled', updated=? WHERE id=?", (_now(), task_id)
            )
            return MindResult(route=fmt, stages=plan.stages, task_id=task_id, answer='Задача отменена')

        structure = self._structure_from_intent(intent, fmt, plan)
        q = validate_structure(structure, fmt)
        if not q.ok:
            self.conn.execute(
                "UPDATE mind_tasks SET status='failed', error=?, updated=? WHERE id=?",
                (','.join(q.issues), _now(), task_id),
            )
            raise ValueError('Структура результата невалидна: ' + ','.join(q.issues))

        user_dir = self.artifacts_root / user_id / task_id
        spec = ArtifactSpec(
            format=fmt,
            title=structure['title'],
            language=intent.language,
            sections=structure.get('sections') or [],
            tables=structure.get('tables'),
            slides=structure.get('slides'),
            sources=structure.get('sources'),
        )
        self.conn.execute(
            "UPDATE mind_tasks SET progress=0.7, updated=? WHERE id=?", (_now(), task_id)
        )
        built = build_artifact(spec, user_dir)
        artifact_id = str(uuid.uuid4())
        self.conn.execute(
            '''INSERT INTO mind_artifacts(
                id, user_id, task_id, format, mime, title, filename, size_bytes, sha256,
                version, status, created, updated, storage_path, meta_json
            ) VALUES (?,?,?,?,?,?,?,?,?,1,'ready',?,?,?,?)''',
            (artifact_id, user_id, task_id, built.format, built.mime, structure['title'],
             built.filename, built.size_bytes, built.sha256, _now(), _now(),
             str(built.path), json.dumps({'route': decision.route}, ensure_ascii=False)),
        )
        self.conn.execute(
            '''UPDATE mind_tasks SET status='done', progress=1, updated=?, result_json=? WHERE id=?''',
            (_now(), json.dumps({'artifact_id': artifact_id}, ensure_ascii=False), task_id),
        )
        msg = {
            'ru': f'Файл {built.filename} готов ({built.size_bytes} байт, SHA-256 {built.sha256[:12]}…).',
            'en': f'File {built.filename} is ready ({built.size_bytes} bytes, SHA-256 {built.sha256[:12]}…).',
        }[intent.language if intent.language in ('ru', 'en') else 'ru']
        return MindResult(
            route=fmt, stages=plan.stages, answer=msg,
            artifact_id=artifact_id, task_id=task_id,
            meta={'sha256': built.sha256, 'filename': built.filename, 'confidence': decision.confidence},
        )

    def _fallback_answer(self, intent, plan) -> str:
        if intent.language == 'ru':
            return (f'Поняла задачу. Маршрут: {plan.route}. '
                    f'Этапы: {", ".join(plan.stages)}. '
                    f'Сформулируйте уточнение или подключите модель Host для полного ответа.')
        return (f'Understood. Route: {plan.route}. '
                f'Stages: {", ".join(plan.stages)}. '
                f'Connect the Host model for a full answer.')

    def _structure_from_intent(self, intent, fmt: str, plan) -> dict:
        title = intent.goal[:80] or ('Документ' if intent.language == 'ru' else 'Document')
        # Strip command verbs for a cleaner title
        for prefix in ('создай ', 'сделай ', 'подготовь ', 'create ', 'make ', 'prepare '):
            if title.lower().startswith(prefix):
                title = title[len(prefix):]
                break
        title = title[:1].upper() + title[1:] if title else title
        pages = plan.params.get('pages') or 3
        slides_n = plan.params.get('slides') or 8
        sections = []
        for i in range(max(1, pages if fmt in ('docx', 'pdf', 'txt') else 3)):
            if intent.language == 'ru':
                sections.append({
                    'heading': f'Раздел {i + 1}',
                    'paragraphs': [
                        f'Это автоматически собранный черновик по запросу: {intent.goal[:200]}.',
                        'Проверьте факты и дополните детали перед использованием.',
                    ],
                    'bullets': [f'Ключевой пункт {i + 1}.1', f'Ключевой пункт {i + 1}.2'],
                })
            else:
                sections.append({
                    'heading': f'Section {i + 1}',
                    'paragraphs': [
                        f'Draft content for: {intent.goal[:200]}.',
                        'Review facts before use.',
                    ],
                    'bullets': [f'Key point {i + 1}.1', f'Key point {i + 1}.2'],
                })
        slides = None
        tables = None
        if fmt == 'pptx':
            slides = []
            for i in range(slides_n):
                slides.append({
                    'title': (f'Слайд {i + 1}' if intent.language == 'ru' else f'Slide {i + 1}') + f': {title[:40]}',
                    'bullets': [
                        f'Пункт {i + 1}.A' if intent.language == 'ru' else f'Point {i + 1}.A',
                        f'Пункт {i + 1}.B' if intent.language == 'ru' else f'Point {i + 1}.B',
                    ],
                    'notes': intent.goal[:200],
                })
        if fmt == 'xlsx':
            tables = [{
                'headers': ['Статья', 'Сумма'] if intent.language == 'ru' else ['Item', 'Amount'],
                'rows': [
                    ['Аренда' if intent.language == 'ru' else 'Rent', 1000],
                    ['Зарплата' if intent.language == 'ru' else 'Payroll', 5000],
                    ['Прочее' if intent.language == 'ru' else 'Other', 750],
                ],
                'add_total': True,
                'allow_formulas': True,
            }]
        return {
            'title': title[:120],
            'sections': sections,
            'slides': slides,
            'tables': tables,
            'sources': [],
        }

    def get_artifact(self, user_id: str, artifact_id: str) -> dict:
        row = self.conn.execute(
            '''SELECT id, user_id, format, mime, title, filename, size_bytes, sha256, status, storage_path, created
               FROM mind_artifacts WHERE id=?''',
            (artifact_id,),
        ).fetchone()
        if not row:
            raise LookupError('Файл не найден')
        assert_owner(row[1], user_id)
        return {
            'id': row[0], 'format': row[2], 'mime': row[3], 'title': row[4],
            'filename': row[5], 'size_bytes': row[6], 'sha256': row[7],
            'status': row[8], 'storage_path': row[9], 'created': row[10],
        }

    def list_artifacts(self, user_id: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            '''SELECT id, format, mime, title, filename, size_bytes, sha256, status, created, version
               FROM mind_artifacts WHERE user_id=? ORDER BY created DESC LIMIT ?''',
            (user_id, int(limit)),
        ).fetchall()
        return [
            {
                'id': r[0], 'format': r[1], 'mime': r[2], 'title': r[3], 'filename': r[4],
                'size_bytes': r[5], 'sha256': r[6], 'status': r[7], 'created': r[8], 'version': r[9],
            }
            for r in rows
        ]

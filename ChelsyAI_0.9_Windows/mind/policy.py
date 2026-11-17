"""Policy / Tool Gateway — rights checked by server code, not by the LLM (SEC-05)."""
from __future__ import annotations

from dataclasses import dataclass

ALLOWED_TOOLS = frozenset({
    'chat_generate',
    'research_search',
    'artifact_build_txt',
    'artifact_build_docx',
    'artifact_build_pdf',
    'artifact_build_pptx',
    'artifact_build_xlsx',
    'memory_read_own',
    'memory_write_own',
})

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_PAGES = 50
MAX_SLIDES = 40
QUEUE_LIMIT = 20
PER_USER_PENDING = 2


@dataclass
class PolicyDecision:
    allowed: bool
    tool: str
    reason: str = ''


def check_tool(tool: str, *, is_admin: bool = False, params: dict | None = None) -> PolicyDecision:
    params = params or {}
    if tool not in ALLOWED_TOOLS:
        return PolicyDecision(False, tool, 'Инструмент не разрешён')
    if tool.startswith('artifact_build_'):
        pages = int(params.get('pages') or 0)
        slides = int(params.get('slides') or 0)
        if pages > MAX_PAGES:
            return PolicyDecision(False, tool, 'Слишком много страниц')
        if slides > MAX_SLIDES:
            return PolicyDecision(False, tool, 'Слишком много слайдов')
    # Admins do not get extra content tools
    return PolicyDecision(True, tool, 'ok')


def assert_owner(object_user_id: str, requester_id: str) -> None:
    if object_user_id != requester_id:
        raise PermissionError('Доступ запрещён: объект принадлежит другому пользователю')

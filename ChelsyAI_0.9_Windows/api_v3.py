"""Host API v3 (0.9.4): own Auth, cabinet, artifacts, admin — no Supabase/Tailscale required."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

import core
from auth import (
    AuthError, authenticate_user, change_email, change_password, create_user,
    create_session, ensure_bootstrap_admins, get_user, is_admin, list_sessions,
    list_users_admin, resolve_access_token, refresh_session, revoke_all_sessions,
    revoke_session, set_user_status, storage_key_for, update_profile,
)
from auth import accounts as accounts_mod
from mind import MindEngine

VERSION = '0.9.4'
UUID_RE = re.compile(r'^[0-9a-fA-F-]{36}$')


def artifacts_root() -> Path:
    root = Path(core.DATA) / 'artifacts'
    root.mkdir(parents=True, exist_ok=True)
    return root


def db():
    """Return a live SQLite connection (caller must commit; close when done).

    Ensures migrations via a short core.db() enter/exit, then opens a dedicated
    connection for multi-statement auth/mind handlers.
    """
    with core.db():
        pass
    conn = sqlite3.connect(core.DB_PATH, timeout=15)
    conn.execute('PRAGMA busy_timeout=15000')
    return conn


def json_body(handler, limit=20000):
    length_text = handler.headers.get('Content-Length', '')
    try:
        length = int(length_text)
    except ValueError:
        handler.reply(411, {'error': 'Content-Length required'})
        return None
    if length < 2 or length > limit:
        handler.reply(413, {'error': 'Request too large'})
        return None
    try:
        data = json.loads(handler.rfile.read(length))
    except (ValueError, UnicodeDecodeError):
        handler.reply(400, {'error': 'Invalid JSON'})
        return None
    if not isinstance(data, dict):
        handler.reply(400, {'error': 'JSON object required'})
        return None
    return data


def bearer(handler) -> str | None:
    header = handler.headers.get('Authorization', '')
    if header.startswith('Bearer '):
        return header[7:].strip()
    # Cookie session (WEB-04) — HttpOnly cookie set by login
    cookie = handler.headers.get('Cookie', '')
    for part in cookie.split(';'):
        part = part.strip()
        if part.startswith('chelsy_access='):
            return part.split('=', 1)[1].strip()
    return None


def current_user(handler) -> dict | None:
    token = bearer(handler)
    if not token:
        handler.reply(401, {'error': 'auth_required', 'message': 'Требуется вход'})
        return None
    conn = db()
    session = resolve_access_token(conn, token)
    if not session:
        handler.reply(401, {'error': 'auth_required', 'message': 'Сессия истекла или отозвана'})
        return None
    user = get_user(conn, session['user_id'])
    if not user or user['status'] != 'active':
        handler.reply(401, {'error': 'auth_required', 'message': 'Аккаунт недоступен'})
        return None
    user['session_id'] = session['session_id']
    user['storage_key'] = storage_key_for(user['id'])
    return user


def require_admin(handler) -> dict | None:
    user = current_user(handler)
    if not user:
        return None
    if not user.get('is_admin'):
        handler.reply(403, {'error': 'forbidden', 'message': 'Нужны права администратора'})
        return None
    return user


def set_auth_cookies(handler, tokens: dict, *, secure: bool = True):
    """Set HttpOnly cookies for browser cabinet (SEC-02)."""
    access = tokens['access_token']
    refresh = tokens['refresh_token']
    parts = [
        f'chelsy_access={access}; Path=/; HttpOnly; SameSite=Strict; Max-Age={tokens["access_expires_in"]}',
        f'chelsy_refresh={refresh}; Path=/api/v3/auth; HttpOnly; SameSite=Strict; Max-Age={tokens["refresh_expires_in"]}',
    ]
    if secure:
        parts = [p + '; Secure' for p in parts]
    for p in parts:
        handler.send_header('Set-Cookie', p)


def handle_public(handler, method: str, path: str) -> bool:
    """Return True if handled. Public auth endpoints + health."""
    if path == '/api/v3/health' and method == 'GET':
        conn = db()
        ensure_bootstrap_admins(conn)
        conn.commit()
        handler.reply(200, {
            'service': 'Chelsy AI Host',
            'version': VERSION,
            'ok': True,
            'auth': 'own',
            'supabase_required': False,
            'tailscale_required': False,
        })
        return True

    if path == '/api/v3/auth/register' and method == 'POST':
        # Public self-registration only if explicitly enabled (NET-03 mail / local policy)
        if os.environ.get('CHELSY_ALLOW_PUBLIC_REGISTER', '0') != '1':
            handler.reply(403, {
                'error': 'registration_disabled',
                'message': 'Публичная регистрация отключена. Аккаунт создаёт администратор Host.',
            })
            return True
        body = json_body(handler)
        if body is None:
            return True
        try:
            conn = db()
            user = create_user(conn, body.get('email', ''), body.get('password', ''),
                               display_name=str(body.get('display_name') or '')[:80])
            tokens = create_session(conn, user['id'], device_label='web',
                                    user_agent=handler.headers.get('User-Agent', '')[:240],
                                    source_ip=handler.client_address[0])
            conn.commit()
            data = json.dumps({'user': {k: user[k] for k in ('id', 'email', 'display_name', 'role')},
                               **tokens}, ensure_ascii=False).encode('utf-8')
            handler.send_response(201)
            handler.send_header('Content-Type', 'application/json; charset=utf-8')
            handler.send_header('Cache-Control', 'no-store')
            set_auth_cookies(handler, tokens, secure=handler.headers.get('X-Forwarded-Proto') == 'https'
                             or os.environ.get('CHELSY_COOKIE_SECURE', '0') == '1')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        except AuthError as exc:
            handler.reply(400, {'error': 'auth_error', 'message': str(exc)})
        return True

    if path == '/api/v3/auth/login' and method == 'POST':
        body = json_body(handler)
        if body is None:
            return True
        try:
            conn = db()
            ensure_bootstrap_admins(conn)
            user = authenticate_user(conn, body.get('email', ''), body.get('password', ''),
                                     source=handler.client_address[0])
            tokens = create_session(
                conn, user['id'], is_admin=user['is_admin'],
                device_label=str(body.get('device_label') or 'client')[:120],
                user_agent=handler.headers.get('User-Agent', '')[:240],
                source_ip=handler.client_address[0],
            )
            conn.commit()
            payload = {
                'user': {
                    'id': user['id'], 'email': user['email'], 'display_name': user['display_name'],
                    'role': user['role'], 'is_admin': user['is_admin'],
                    'storage_key': user['storage_key'],
                },
                **tokens,
            }
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/json; charset=utf-8')
            handler.send_header('Cache-Control', 'no-store')
            set_auth_cookies(handler, tokens, secure=handler.headers.get('X-Forwarded-Proto') == 'https'
                             or os.environ.get('CHELSY_COOKIE_SECURE', '0') == '1')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        except AuthError as exc:
            handler.reply(401, {'error': 'auth_error', 'message': str(exc)})
        return True

    if path == '/api/v3/auth/refresh' and method == 'POST':
        body = json_body(handler) or {}
        refresh = (body or {}).get('refresh_token')
        if not refresh:
            cookie = handler.headers.get('Cookie', '')
            for part in cookie.split(';'):
                part = part.strip()
                if part.startswith('chelsy_refresh='):
                    refresh = part.split('=', 1)[1].strip()
        try:
            conn = db()
            tokens = refresh_session(conn, refresh or '')
            conn.commit()
            user = get_user(conn, tokens.pop('user_id'))
            tokens.pop('is_admin', None)
            payload = {'user': user, **tokens}
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/json; charset=utf-8')
            set_auth_cookies(handler, tokens, secure=os.environ.get('CHELSY_COOKIE_SECURE', '0') == '1')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        except ValueError:
            handler.reply(401, {'error': 'invalid_refresh', 'message': 'Сессия недействительна'})
        return True

    return False


def handle_authed(handler, method: str, path: str) -> bool:
    if not path.startswith('/api/v3/'):
        return False
    # logout
    if path == '/api/v3/auth/logout' and method == 'POST':
        user = current_user(handler)
        if not user:
            return True
        conn = db()
        revoke_session(conn, user['session_id'], user['id'])
        conn.commit()
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json; charset=utf-8')
        handler.send_header('Set-Cookie', 'chelsy_access=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict')
        handler.send_header('Set-Cookie', 'chelsy_refresh=; Path=/api/v3/auth; Max-Age=0; HttpOnly; SameSite=Strict')
        data = b'{"ok":true}'
        handler.send_header('Content-Length', str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        return True

    if path == '/api/v3/me' and method == 'GET':
        user = current_user(handler)
        if user:
            handler.reply(200, {'user': user, 'version': VERSION})
        return True

    if path == '/api/v3/me' and method == 'POST':
        user = current_user(handler)
        if not user:
            return True
        body = json_body(handler)
        if body is None:
            return True
        conn = db()
        updated = accounts_mod.update_profile(
            conn, user['id'],
            display_name=body.get('display_name', user['display_name']),
            locale=body.get('locale', user['locale']),
            timezone=body.get('timezone', user['timezone']),
            memory_enabled=body.get('memory_enabled', user['memory_enabled']),
        )
        conn.commit()
        handler.reply(200, {'user': updated})
        return True

    if path == '/api/v3/me/password' and method == 'POST':
        user = current_user(handler)
        if not user:
            return True
        body = json_body(handler)
        if body is None:
            return True
        try:
            conn = db()
            change_password(conn, user['id'], body.get('current_password', ''), body.get('new_password', ''))
            revoke_all_sessions(conn, user['id'])
            tokens = create_session(conn, user['id'], is_admin=user['is_admin'], device_label='password-change')
            conn.commit()
            handler.reply(200, {'ok': True, **tokens})
        except AuthError as exc:
            handler.reply(400, {'error': 'auth_error', 'message': str(exc)})
        return True

    if path == '/api/v3/me/email' and method == 'POST':
        user = current_user(handler)
        if not user:
            return True
        body = json_body(handler)
        if body is None:
            return True
        try:
            conn = db()
            change_email(conn, user['id'], body.get('password', ''), body.get('new_email', ''))
            revoke_all_sessions(conn, user['id'])
            conn.commit()
            handler.reply(200, {'ok': True, 'message': 'Email изменён. Войдите снова. Подтверждение нового адреса — по политике Host.'})
        except AuthError as exc:
            handler.reply(400, {'error': 'auth_error', 'message': str(exc)})
        return True

    if path == '/api/v3/me/sessions' and method == 'GET':
        user = current_user(handler)
        if not user:
            return True
        handler.reply(200, {'sessions': list_sessions(db(), user['id'])})
        return True

    if path.startswith('/api/v3/me/sessions/') and method == 'DELETE':
        user = current_user(handler)
        if not user:
            return True
        sid = path.rsplit('/', 1)[-1]
        conn = db()
        ok = revoke_session(conn, sid, user['id'])
        conn.commit()
        handler.reply(200 if ok else 404, {'revoked': ok})
        return True

    if path == '/api/v3/me/sessions' and method == 'DELETE':
        user = current_user(handler)
        if not user:
            return True
        conn = db()
        n = revoke_all_sessions(conn, user['id'], except_id=user['session_id'])
        conn.commit()
        handler.reply(200, {'revoked': n})
        return True

    # ---- overview / cabinet
    if path == '/api/v3/cabinet/overview' and method == 'GET':
        user = current_user(handler)
        if not user:
            return True
        conn = db()
        tasks = conn.execute(
            "SELECT COUNT(*) FROM mind_tasks WHERE user_id=? AND status IN ('queued','running')",
            (user['id'],),
        ).fetchone()[0]
        files = conn.execute(
            'SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM mind_artifacts WHERE user_id=?',
            (user['id'],),
        ).fetchone()
        import ollama_client
        handler.reply(200, {
            'host': {'version': VERSION, 'ollama': ollama_client.available()},
            'tasks_active': tasks,
            'files_count': files[0],
            'files_bytes': files[1],
            'quota_mb_used': user['quota_mb_used'],
            'quota_mb_limit': user['quota_mb_limit'],
            'host_reachable': True,
        })
        return True

    # ---- mind / artifacts
    if path == '/api/v3/mind/run' and method == 'POST':
        user = current_user(handler)
        if not user:
            return True
        body = json_body(handler, limit=70000)
        if body is None:
            return True
        text = body.get('message') or body.get('text') or ''
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            handler.reply(400, {'error': 'invalid_message'})
            return True
        conn = db()
        engine = MindEngine(conn, artifacts_root())

        def generate_text(prompt, plan):
            try:
                from intelligence import IntelligenceEngine
                # Prefer existing intelligence stack when available
                ie = IntelligenceEngine(conn if False else None)  # may not take conn
            except Exception:
                ie = None
            try:
                import ollama_client
                if ollama_client.available():
                    # lightweight non-stream call
                    from ollama_client import chat
                    messages = [
                        {'role': 'system', 'content': f'Ты Chelsy. Язык: {plan.params.get("language")}. Кратко и по делу.'},
                        {'role': 'user', 'content': prompt},
                    ]
                    # chat API may differ — fall back
                    if hasattr(ollama_client, 'chat'):
                        return ollama_client.chat(messages) or ''
            except Exception:
                pass
            return ''

        try:
            result = engine.handle(
                user['id'], text.strip(),
                idempotency_key=str(body.get('idempotency_key') or ''),
                generate_text=generate_text if body.get('use_model', True) else None,
            )
            conn.commit()
            handler.reply(200, {
                'route': result.route,
                'stages': result.stages,
                'answer': result.answer,
                'artifact_id': result.artifact_id,
                'task_id': result.task_id,
                'meta': result.meta,
            })
        except PermissionError as exc:
            handler.reply(403, {'error': 'forbidden', 'message': str(exc)})
        except RuntimeError as exc:
            handler.reply(429, {'error': 'busy', 'message': str(exc)})
        except ValueError as exc:
            handler.reply(400, {'error': 'invalid', 'message': str(exc)})
        except Exception as exc:
            handler.reply(500, {'error': 'internal', 'message': 'Ошибка Mind Engine', 'detail': type(exc).__name__})
        return True

    if path == '/api/v3/artifacts' and method == 'GET':
        user = current_user(handler)
        if not user:
            return True
        engine = MindEngine(db(), artifacts_root())
        handler.reply(200, {'artifacts': engine.list_artifacts(user['id'])})
        return True

    m = re.fullmatch(r'/api/v3/artifacts/([0-9a-fA-F-]{36})(?:/(download))?', path)
    if m and method == 'GET':
        user = current_user(handler)
        if not user:
            return True
        engine = MindEngine(db(), artifacts_root())
        try:
            art = engine.get_artifact(user['id'], m.group(1))
        except (LookupError, PermissionError):
            handler.reply(404, {'error': 'not_found'})
            return True
        if m.group(2) == 'download':
            path_file = Path(art['storage_path'])
            if not path_file.is_file():
                handler.reply(410, {'error': 'missing_file', 'message': 'Файл отсутствует на диске'})
                return True
            data = path_file.read_bytes()
            handler.send_response(200)
            handler.send_header('Content-Type', art['mime'])
            handler.send_header('Content-Length', str(len(data)))
            handler.send_header('Content-Disposition', f'attachment; filename="{art["filename"]}"')
            handler.send_header('X-Content-Type-Options', 'nosniff')
            handler.send_header('Cache-Control', 'no-store')
            handler.end_headers()
            handler.wfile.write(data)
            return True
        # metadata only — never leak other users via IDOR
        public = {k: art[k] for k in art if k != 'storage_path'}
        handler.reply(200, {'artifact': public})
        return True

    if m and method == 'DELETE':
        user = current_user(handler)
        if not user:
            return True
        conn = db()
        engine = MindEngine(conn, artifacts_root())
        try:
            art = engine.get_artifact(user['id'], m.group(1))
        except (LookupError, PermissionError):
            handler.reply(404, {'error': 'not_found'})
            return True
        Path(art['storage_path']).unlink(missing_ok=True)
        conn.execute('DELETE FROM mind_artifacts WHERE id=? AND user_id=?', (art['id'], user['id']))
        conn.commit()
        handler.reply(200, {'deleted': True})
        return True

    # ---- admin (no private content)
    if path == '/api/v3/admin/users' and method == 'GET':
        admin = require_admin(handler)
        if not admin:
            return True
        handler.reply(200, {'users': list_users_admin(db())})
        return True

    if path == '/api/v3/admin/users' and method == 'POST':
        admin = require_admin(handler)
        if not admin:
            return True
        body = json_body(handler)
        if body is None:
            return True
        try:
            conn = db()
            user = create_user(
                conn, body.get('email', ''), body.get('password', ''),
                display_name=str(body.get('display_name') or '')[:80],
                role='user', created_by=admin['id'],
            )
            conn.commit()
            handler.reply(201, {'user': user})
        except AuthError as exc:
            handler.reply(400, {'error': 'auth_error', 'message': str(exc)})
        return True

    if path.startswith('/api/v3/admin/users/') and path.endswith('/status') and method == 'POST':
        admin = require_admin(handler)
        if not admin:
            return True
        uid = path.split('/')[4]
        if not UUID_RE.match(uid):
            handler.reply(400, {'error': 'bad_id'})
            return True
        body = json_body(handler) or {}
        try:
            conn = db()
            set_user_status(conn, admin['id'], uid, body.get('status', ''), reason=str(body.get('reason') or ''))
            if body.get('status') == 'blocked':
                revoke_all_sessions(conn, uid)
            conn.commit()
            handler.reply(200, {'ok': True})
        except AuthError as exc:
            handler.reply(400, {'error': 'auth_error', 'message': str(exc)})
        return True

    if path == '/api/v3/admin/status' and method == 'GET':
        admin = require_admin(handler)
        if not admin:
            return True
        conn = db()
        sessions = conn.execute(
            'SELECT COUNT(*) FROM auth_sessions WHERE revoked=0 AND access_expires > ?',
            (time.time(),),
        ).fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM auth_users WHERE status='active'").fetchone()[0]
        queue = conn.execute(
            "SELECT COUNT(*) FROM mind_tasks WHERE status IN ('queued','running')"
        ).fetchone()[0]
        import ollama_client
        handler.reply(200, {
            'version': VERSION,
            'active_sessions': sessions,
            'active_users': users,
            'queue_len': queue,
            'ollama': ollama_client.available(),
            # Explicitly no message content fields
            'privacy': 'admin_cannot_read_user_content',
        })
        return True

    if path == '/api/v3/admin/errors' and method == 'GET':
        admin = require_admin(handler)
        if not admin:
            return True
        rows = db().execute(
            'SELECT at, code, module, request_id, category, message FROM host_error_log '
            'ORDER BY id DESC LIMIT 100'
        ).fetchall()
        handler.reply(200, {
            'errors': [
                {'at': r[0], 'code': r[1], 'module': r[2], 'request_id': r[3],
                 'category': r[4], 'message': r[5]}
                for r in rows
            ]
        })
        return True

    # Unknown v3
    if path.startswith('/api/v3/'):
        handler.reply(404, {'error': 'not_found'})
        return True
    return False

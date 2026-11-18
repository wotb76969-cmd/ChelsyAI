"""Own user accounts, dual-admin model (ADM-01 / SEC-04)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from .crypto_keys import generate_user_key, wrap_user_key
from .passwords import hash_password, verify_password, validate_password_policy, needs_rehash, PasswordError
from . import rate_limit

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
MAX_ADMINS = 2


class AuthError(Exception):
    """Public auth failure — never reveal whether email exists (SEC-02)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def storage_key_for(user_id: str) -> str:
    return 'u:' + user_id


def _norm_email(email: str) -> str:
    return (email or '').strip().lower()


def create_user(conn: sqlite3.Connection, email: str, password: str, *,
                display_name: str = '', role: str = 'user',
                created_by: str = 'self') -> dict:
    email = _norm_email(email)
    if not EMAIL_RE.match(email):
        raise AuthError('Некорректный email')
    try:
        validate_password_policy(password)
    except PasswordError as exc:
        raise AuthError(str(exc)) from exc
    if role == 'admin':
        n = conn.execute(
            "SELECT COUNT(*) FROM auth_users WHERE role='admin' AND status!='deleted'"
        ).fetchone()[0]
        if n >= MAX_ADMINS:
            raise AuthError('Уже есть два администратора')
    existing = conn.execute('SELECT id FROM auth_users WHERE email=?', (email,)).fetchone()
    if existing:
        raise AuthError('Не удалось создать аккаунт')  # do not reveal duplicate
    user_id = str(uuid.uuid4())
    pwd_hash = hash_password(password)
    user_key = generate_user_key()
    wrapped = wrap_user_key(user_key, password)
    conn.execute(
        '''INSERT INTO auth_users(
            id, email, password_hash, display_name, role, status, created, updated,
            email_verified, key_wrap_json, created_by, locale, timezone, memory_enabled
        ) VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,1)''',
        (user_id, email, pwd_hash, (display_name or email.split('@')[0])[:80],
         role if role in ('user', 'admin') else 'user', 'active', _now(), _now(),
         json.dumps(wrapped), created_by, 'ru', 'UTC'),
    )
    conn.execute(
        'INSERT INTO auth_audit(id, at, actor_id, action, object_type, object_id, result, detail) '
        'VALUES (?,?,?,?,?,?,?,?)',
        (str(uuid.uuid4()), _now(), created_by, 'user.create', 'user', user_id, 'ok',
         json.dumps({'role': role}, ensure_ascii=False)),
    )
    return {'id': user_id, 'email': email, 'role': role, 'display_name': display_name}


def authenticate_user(conn: sqlite3.Connection, email: str, password: str, *,
                      source: str = '') -> dict:
    email_n = _norm_email(email)
    allowed, delay = rate_limit.allow_login_attempt(email_n, source)
    if not allowed:
        raise AuthError('Слишком много попыток. Попробуйте позже.')
    if delay:
        import time
        time.sleep(min(delay, 2.0))  # small backoff; clients should also wait
    row = conn.execute(
        '''SELECT id, email, password_hash, role, status, display_name, key_wrap_json
           FROM auth_users WHERE email=?''',
        (email_n,),
    ).fetchone()
    # Constant-ish failure path
    if not row or row[4] in ('deleted', 'disabled'):
        rate_limit.register_failure(email_n, source)
        raise AuthError('Неверный email или пароль')
    user_id, email_db, pwd_hash, role, status, display_name, key_wrap = row
    if status == 'blocked':
        rate_limit.register_failure(email_n, source)
        raise AuthError('Неверный email или пароль')
    if not verify_password(pwd_hash, password):
        rate_limit.register_failure(email_n, source)
        raise AuthError('Неверный email или пароль')
    rate_limit.register_success(email_n)
    migrated=pwd_hash.startswith(('$2a$','$2b$','$2y$'))
    if migrated and not key_wrap:
        wrapped=wrap_user_key(generate_user_key(),password)
        conn.execute("UPDATE auth_users SET key_wrap_json=? WHERE id=? AND key_wrap_json=''",(json.dumps(wrapped),user_id))
    try:
        validate_password_policy(password)
        strong=True
    except PasswordError:
        strong=False
        conn.execute('INSERT OR IGNORE INTO required_password_change VALUES(?)',(user_id,))
    if strong and (migrated or needs_rehash(pwd_hash)):
        conn.execute(
            'UPDATE auth_users SET password_hash=?, updated=? WHERE id=?',
            (hash_password(password), _now(), user_id),
        )
    return {
        'id': user_id,
        'email': email_db,
        'role': role,
        'display_name': display_name,
        'is_admin': role == 'admin',
        'storage_key': storage_key_for(user_id),
    }


def get_user(conn: sqlite3.Connection, user_id: str) -> dict | None:
    row = conn.execute(
        '''SELECT id, email, role, status, display_name, created, updated, email_verified,
                  locale, timezone, memory_enabled, avatar_path, quota_mb_used, quota_mb_limit
           FROM auth_users WHERE id=?''',
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {
        'id': row[0], 'email': row[1], 'role': row[2], 'status': row[3],
        'display_name': row[4], 'created': row[5], 'updated': row[6],
        'email_verified': bool(row[7]), 'locale': row[8], 'timezone': row[9],
        'memory_enabled': bool(row[10]), 'avatar_path': row[11] or '',
        'quota_mb_used': row[12] or 0, 'quota_mb_limit': row[13] or 512,
        'is_admin': row[2] == 'admin',
        'storage_key': storage_key_for(row[0]),
    }


def is_admin(conn: sqlite3.Connection, user_id: str) -> bool:
    row = conn.execute(
        "SELECT role, status FROM auth_users WHERE id=?", (user_id,)
    ).fetchone()
    return bool(row and row[0] == 'admin' and row[1] == 'active')


def list_users_admin(conn: sqlite3.Connection, limit: int = 500) -> list[dict]:
    """Admin view: identity/status/quotas only — NEVER chat/file content."""
    rows = conn.execute(
        '''SELECT id, email, role, status, display_name, created, updated,
                  quota_mb_used, quota_mb_limit
           FROM auth_users WHERE status!='deleted' ORDER BY created LIMIT ?''',
        (max(1, min(int(limit), 2000)),),
    ).fetchall()
    return [
        {
            'id': r[0], 'email': r[1], 'role': r[2], 'status': r[3],
            'display_name': r[4], 'created': r[5], 'updated': r[6],
            'quota_mb_used': r[7] or 0, 'quota_mb_limit': r[8] or 512,
        }
        for r in rows
    ]


def set_user_status(conn: sqlite3.Connection, actor_id: str, user_id: str,
                    status: str, reason: str = '') -> None:
    if status not in ('active', 'blocked', 'disabled', 'deleted'):
        raise AuthError('Недопустимый статус')
    target = get_user(conn, user_id)
    if not target:
        raise AuthError('Пользователь не найден')
    if target['role'] == 'admin' and status in ('blocked', 'deleted', 'disabled'):
        # dual confirmation needed for removing admin — soft guard
        raise AuthError('Смена статуса администратора требует совместного подтверждения')
    conn.execute(
        'UPDATE auth_users SET status=?, updated=? WHERE id=?',
        (status, _now(), user_id),
    )
    conn.execute(
        'INSERT INTO auth_audit(id, at, actor_id, action, object_type, object_id, result, detail) '
        'VALUES (?,?,?,?,?,?,?,?)',
        (str(uuid.uuid4()), _now(), actor_id, 'user.status', 'user', user_id, 'ok',
         json.dumps({'status': status, 'reason': reason[:200]}, ensure_ascii=False)),
    )


def change_password(conn: sqlite3.Connection, user_id: str, current: str, new: str) -> None:
    row = conn.execute(
        'SELECT password_hash, key_wrap_json FROM auth_users WHERE id=?', (user_id,)
    ).fetchone()
    if not row or not verify_password(row[0], current):
        raise AuthError('Неверный текущий пароль')
    try:
        validate_password_policy(new)
    except PasswordError as exc:
        raise AuthError(str(exc)) from exc
    # Re-wrap content key with new password (need unwrap with old)
    from .crypto_keys import unwrap_user_key, wrap_user_key
    try:
        key = unwrap_user_key(json.loads(row[1] or '{}'), current)
        wrapped = wrap_user_key(key, new)
    except Exception as exc:
        raise AuthError('Не удалось обновить защиту ключа') from exc
    conn.execute(
        'UPDATE auth_users SET password_hash=?, key_wrap_json=?, updated=? WHERE id=?',
        (hash_password(new), json.dumps(wrapped), _now(), user_id),
    )


def change_email(conn: sqlite3.Connection, user_id: str, password: str, new_email: str) -> None:
    new_email = _norm_email(new_email)
    if not EMAIL_RE.match(new_email):
        raise AuthError('Некорректный email')
    row = conn.execute(
        'SELECT password_hash FROM auth_users WHERE id=?', (user_id,)
    ).fetchone()
    if not row or not verify_password(row[0], password):
        raise AuthError('Неверный пароль')
    if conn.execute('SELECT 1 FROM auth_users WHERE email=?', (new_email,)).fetchone():
        raise AuthError('Не удалось сменить email')
    conn.execute(
        'UPDATE auth_users SET email=?, email_verified=0, updated=? WHERE id=?',
        (new_email, _now(), user_id),
    )


def update_profile(conn: sqlite3.Connection, user_id: str, **fields) -> dict:
    allowed = {'display_name', 'locale', 'timezone', 'memory_enabled', 'avatar_path'}
    sets = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == 'display_name':
            value = str(value)[:80]
        if key == 'memory_enabled':
            value = 1 if value else 0
        sets.append(f'{key}=?')
        values.append(value)
    if not sets:
        return get_user(conn, user_id)
    sets.append('updated=?')
    values.append(_now())
    values.append(user_id)
    conn.execute(f'UPDATE auth_users SET {", ".join(sets)} WHERE id=?', values)
    return get_user(conn, user_id)

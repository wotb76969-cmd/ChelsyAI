"""Opaque access/refresh sessions stored on Host (SEC-02)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone

from .passwords import new_token

ACCESS_TTL_SEC = 10 * 60          # 10 minutes
REFRESH_TTL_SEC = 30 * 24 * 3600  # 30 days
ADMIN_IDLE_TTL_SEC = 15 * 60      # 15 minutes idle for admin sessions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: str, *,
                   is_admin: bool = False, device_label: str = '',
                   user_agent: str = '', source_ip: str = '') -> dict:
    access = new_token(24)
    refresh = new_token(32)
    now = time.time()
    access_exp = now + ACCESS_TTL_SEC
    refresh_exp = now + REFRESH_TTL_SEC
    sid = new_token(16)
    conn.execute(
        '''INSERT INTO auth_sessions(
            id, user_id, access_hash, refresh_hash, access_expires, refresh_expires,
            created, last_seen, device_label, user_agent, source_ip, is_admin, revoked
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)''',
        (sid, user_id, _hash(access), _hash(refresh), access_exp, refresh_exp,
         _now(), _now(), device_label[:120], user_agent[:240], source_ip[:64],
         1 if is_admin else 0),
    )
    return {
        'session_id': sid,
        'access_token': access,
        'refresh_token': refresh,
        'access_expires_in': ACCESS_TTL_SEC,
        'refresh_expires_in': REFRESH_TTL_SEC,
        'token_type': 'Bearer',
    }


def resolve_access_token(conn: sqlite3.Connection, token: str) -> dict | None:
    if not token or len(token) < 20 or len(token) > 200:
        return None
    row = conn.execute(
        '''SELECT id, user_id, access_expires, last_seen, is_admin, revoked
           FROM auth_sessions WHERE access_hash=?''',
        (_hash(token),),
    ).fetchone()
    if not row:
        return None
    sid, user_id, access_exp, last_seen, is_admin, revoked = row
    if revoked:
        return None
    now = time.time()
    if now > float(access_exp):
        return None
    if is_admin:
        # idle timeout for admin sessions
        try:
            last = datetime.fromisoformat(last_seen).timestamp()
        except ValueError:
            last = 0
        if now - last > ADMIN_IDLE_TTL_SEC:
            conn.execute('UPDATE auth_sessions SET revoked=1 WHERE id=?', (sid,))
            return None
    conn.execute('UPDATE auth_sessions SET last_seen=? WHERE id=?', (_now(), sid))
    return {'session_id': sid, 'user_id': user_id, 'is_admin': bool(is_admin)}


def refresh_session(conn: sqlite3.Connection, refresh_token: str) -> dict:
    """Rotate refresh token; reuse detection revokes the family."""
    if not isinstance(refresh_token,str) or not 20 <= len(refresh_token) <= 200:
        raise ValueError('invalid_refresh')
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    h = _hash(refresh_token)
    reused = conn.execute('SELECT session_id FROM used_refresh WHERE digest=?',(h,)).fetchone()
    if reused:
        conn.execute('UPDATE auth_sessions SET revoked=1 WHERE id=?',reused)
        raise ValueError('refresh_reuse')
    row = conn.execute(
        '''SELECT id, user_id, refresh_expires, refresh_hash, is_admin, revoked, refresh_family, last_seen
           FROM auth_sessions WHERE refresh_hash=? OR previous_refresh_hash=?''',
        (h, h),
    ).fetchone()
    if not row:
        raise ValueError('invalid_refresh')
    sid, user_id, refresh_exp, current_hash, is_admin, revoked, family, seen = row
    active = conn.execute("SELECT 1 FROM auth_users WHERE id=? AND status='active'",(user_id,)).fetchone()
    if not active or (is_admin and time.time()-datetime.fromisoformat(seen).timestamp()>ADMIN_IDLE_TTL_SEC):
        conn.execute('UPDATE auth_sessions SET revoked=1 WHERE id=?',(sid,))
        raise ValueError('invalid_refresh')
    if revoked or time.time() > float(refresh_exp):
        raise ValueError('invalid_refresh')
    # Reuse of an already-rotated token → revoke family
    if h != current_hash:
        conn.execute(
            'UPDATE auth_sessions SET revoked=1 WHERE user_id=? AND (id=? OR refresh_family=?)',
            (user_id, sid, family or sid),
        )
        raise ValueError('refresh_reuse')
    access = new_token(24)
    new_refresh = new_token(32)
    now = time.time()
    conn.execute('INSERT INTO used_refresh VALUES(?,?)',(h,sid))
    family = family or sid
    conn.execute(
        '''UPDATE auth_sessions SET access_hash=?, previous_refresh_hash=refresh_hash,
           refresh_hash=?, access_expires=?, refresh_expires=?, last_seen=?, refresh_family=?
           WHERE id=?''',
        (_hash(access), _hash(new_refresh), now + ACCESS_TTL_SEC, refresh_exp,
         _now(), family, sid),
    )
    return {
        'session_id': sid,
        'access_token': access,
        'refresh_token': new_refresh,
        'access_expires_in': ACCESS_TTL_SEC,
        'refresh_expires_in': max(0,int(refresh_exp-now)),
        'token_type': 'Bearer',
        'user_id': user_id,
        'is_admin': bool(is_admin),
    }


def revoke_session(conn: sqlite3.Connection, session_id: str, user_id: str) -> bool:
    cur = conn.execute(
        'UPDATE auth_sessions SET revoked=1 WHERE id=? AND user_id=?',
        (session_id, user_id),
    )
    return cur.rowcount > 0


def revoke_all_sessions(conn: sqlite3.Connection, user_id: str, *, except_id: str | None = None) -> int:
    if except_id:
        cur = conn.execute(
            'UPDATE auth_sessions SET revoked=1 WHERE user_id=? AND id!=?',
            (user_id, except_id),
        )
    else:
        cur = conn.execute('UPDATE auth_sessions SET revoked=1 WHERE user_id=?', (user_id,))
    return cur.rowcount


def list_sessions(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    rows = conn.execute(
        '''SELECT id, created, last_seen, device_label, user_agent, source_ip, revoked, is_admin
           FROM auth_sessions WHERE user_id=? ORDER BY last_seen DESC LIMIT 50''',
        (user_id,),
    ).fetchall()
    return [
        {
            'id': r[0], 'created': r[1], 'last_seen': r[2], 'device_label': r[3],
            'user_agent': r[4], 'source_ip': r[5], 'revoked': bool(r[6]), 'is_admin': bool(r[7]),
        }
        for r in rows
    ]


def purge_expired(conn: sqlite3.Connection) -> int:
    now = time.time()
    cur = conn.execute(
        'DELETE FROM auth_sessions WHERE (revoked=1 AND refresh_expires < ?) OR refresh_expires < ?',
        (now - 7 * 86400, now - 7 * 86400),
    )
    return cur.rowcount

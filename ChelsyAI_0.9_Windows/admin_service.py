"""Chelsy Host administration: accounts, subscriptions, activity and audit through Supabase.

Security model
--------------
* Only Chelsy Host uses the project's SECRET key (sb_secret_… or the legacy service_role JWT).
  It is read from the CHELSY_SUPABASE_SECRET_KEY environment variable or from
  %LOCALAPPDATA%/ChelsyAI/host_admin.json, encrypted for the current Windows user with DPAPI.
  It is never bundled into Desktop, Windows Client, Android or the website and never sent to them.
* Every admin action requires the signed-in Supabase account to be the configured owner
  (admin_user_id) and is written to public.chelsy_admin_audit.
* Accounts are never deleted here (ТЗ: «не удалять пользователей»): they can be blocked and unblocked.
* Activity holds metadata only (kind, route, size, device) — never message text.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

import supabase_auth

PLANS = {'start': 'Start', 'plus': 'Plus', 'pro': 'Pro', 'team': 'Teams'}
PLAN_ORDER = ['start', 'plus', 'pro', 'team']
DEFAULT_LIMITS = {'enabled': False, 'start': 30, 'plus': 300, 'pro': 1000, 'team': 0}   # 0 = no limit
FOREVER_BAN = '876000h'          # 100 years: Supabase's way to block an account without deleting it
MIGRATION_HINT = ('В базе нет таблиц администрирования. Примени миграцию '
                  'supabase/004_admin_subscriptions_activity.sql в Supabase → SQL Editor.')


class AdminError(Exception):
    """A problem the administrator should see (Russian message)."""


# ------------------------------------------------------------------ storage
def _data_dir() -> Path:
    path = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'ChelsyAI'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _secret_path() -> Path:
    return _data_dir() / 'host_admin.json'


def _limits_path() -> Path:
    return _data_dir() / 'plan_limits.json'


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Encrypt/decrypt for the current Windows user (CryptProtectData)."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):   # UI_FORBIDDEN
        raise AdminError('Windows не смог зашифровать/расшифровать ключ (DPAPI).')
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def valid_secret_key(key: str) -> bool:
    key = (key or '').strip()
    if key.startswith('sb_secret_') and 20 <= len(key) <= 200 and re.fullmatch(r'[A-Za-z0-9_\-]+', key):
        return True
    # Legacy service_role JWT: check the role claim without trusting anything else.
    parts = key.split('.')
    if len(parts) == 3 and key.startswith('eyJ'):
        try:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
            return payload.get('role') == 'service_role'
        except (ValueError, TypeError):
            return False
    return False


def save_secret_key(key: str) -> str:
    key = (key or '').strip()
    if key.startswith('sb_publishable_'):
        raise AdminError('Это публичный (publishable) ключ. Нужен секретный: Supabase → Project Settings → API Keys → Secret keys.')
    if not valid_secret_key(key):
        raise AdminError('Ключ не похож на секретный ключ Supabase (sb_secret_… или service_role).')
    if sys.platform == 'win32':
        record = {'protection': 'dpapi', 'secret': base64.b64encode(_dpapi(key.encode('utf-8'), True)).decode('ascii')}
    else:
        record = {'protection': 'file-permissions', 'secret': key}
    path = _secret_path()
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(record), encoding='utf-8')
    if sys.platform != 'win32':
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return 'Секретный ключ сохранён только на этом компьютере' + (' (зашифрован Windows DPAPI).' if sys.platform == 'win32' else '.')


def forget_secret_key():
    try:
        _secret_path().unlink()
    except FileNotFoundError:
        pass


def secret_key() -> str | None:
    env = os.environ.get('CHELSY_SUPABASE_SECRET_KEY', '').strip()
    if env:
        return env if valid_secret_key(env) else None
    try:
        record = json.loads(_secret_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    raw = record.get('secret', '')
    try:
        key = _dpapi(base64.b64decode(raw), False).decode('utf-8') if record.get('protection') == 'dpapi' else raw
    except (AdminError, ValueError, OSError, AttributeError):
        return None
    return key if valid_secret_key(key) else None


def load_limits() -> dict:
    try:
        data = json.loads(_limits_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    limits = dict(DEFAULT_LIMITS)
    limits['enabled'] = bool(data.get('enabled', False))
    for plan in PLAN_ORDER:
        try:
            limits[plan] = max(0, min(100000, int(data.get(plan, DEFAULT_LIMITS[plan]))))
        except (TypeError, ValueError):
            pass
    return limits


def save_limits(limits: dict) -> dict:
    clean = dict(DEFAULT_LIMITS)
    clean['enabled'] = bool(limits.get('enabled'))
    for plan in PLAN_ORDER:
        clean[plan] = max(0, min(100000, int(limits.get(plan, DEFAULT_LIMITS[plan]) or 0)))
    _limits_path().write_text(json.dumps(clean), encoding='utf-8')
    return clean


# ------------------------------------------------------------------ HTTP
def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _uuid(value) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise AdminError('Некорректный идентификатор пользователя.') from None


class SupabaseAdmin:
    """Thin client for the Supabase Auth Admin API and PostgREST with the secret key."""

    def __init__(self, url: str | None = None, key: str | None = None, opener=None, timeout: float = 12):
        cfg = None
        if url is None:
            try:
                cfg = supabase_auth.config()
            except supabase_auth.AuthError as exc:
                raise AdminError('Настройки Supabase на хосте неверны: ' + str(exc)) from exc
            if cfg is None:
                supabase_auth.allow_bundled_config(True)
                cfg = supabase_auth.config()
            if cfg is None:
                raise AdminError('Supabase не настроен на хосте. Запусти «Chelsy AI — настройка Supabase».')
        self.url = (url or cfg[0]).rstrip('/')
        self.key = key if key is not None else secret_key()
        if not self.key:
            raise AdminError('На хосте не задан секретный ключ Supabase. Открой вкладку «Настройки» админ-панели.')
        self.opener = opener or build_opener()
        self.timeout = timeout

    # -- transport
    def _request(self, method: str, path: str, *, params=None, body=None, prefer=None):
        url = self.url + path + (('?' + urlencode(params, safe=',.()*:')) if params else '')
        headers = {'apikey': self.key, 'Accept': 'application/json'}
        if not self.key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + self.key       # legacy service_role JWT
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if prefer:
            headers['Prefer'] = prefer
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = ''
            try:
                detail = json.loads(exc.read() or b'{}')
            except (ValueError, OSError):
                pass
            message = json.dumps(detail, ensure_ascii=False)[:300] if detail else ''
            if exc.code in (401, 403):
                raise AdminError('Supabase отклонил секретный ключ (HTTP %d). Проверь ключ во вкладке «Настройки».' % exc.code) from exc
            if (exc.code == 404 and path.startswith('/rest/v1/chelsy_')) or 'PGRST205' in message or '42P01' in message:
                raise AdminError(MIGRATION_HINT) from exc
            raise AdminError(f'Supabase вернул ошибку HTTP {exc.code}. {message}'.strip()) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AdminError('Supabase недоступен: проверь подключение к интернету.') from exc

    # -- health
    def check(self) -> str:
        self._request('GET', '/auth/v1/admin/users', params={'page': 1, 'per_page': 1})
        self._request('GET', '/rest/v1/chelsy_subscriptions', params={'select': 'id', 'limit': 1})
        return 'Подключение к Supabase работает, таблицы администрирования на месте.'

    # -- accounts (Auth Admin API)
    def list_users(self, page: int = 1, per_page: int = 200) -> list[dict]:
        data = self._request('GET', '/auth/v1/admin/users', params={'page': page, 'per_page': per_page}) or {}
        return data.get('users', []) if isinstance(data, dict) else []

    def all_users(self, limit: int = 2000) -> list[dict]:
        users, page = [], 1
        while len(users) < limit:
            chunk = self.list_users(page, 200)
            users += chunk
            if len(chunk) < 200:
                break
            page += 1
        return users[:limit]

    def get_user(self, user_id: str) -> dict:
        return self._request('GET', '/auth/v1/admin/users/' + _uuid(user_id)) or {}

    def update_user(self, user_id: str, changes: dict) -> dict:
        return self._request('PUT', '/auth/v1/admin/users/' + _uuid(user_id), body=changes) or {}

    def send_recovery(self, email: str):
        self._request('POST', '/auth/v1/recover', body={'email': email})

    # -- PostgREST tables
    def select(self, table: str, **params) -> list[dict]:
        return self._request('GET', '/rest/v1/' + table, params=params) or []

    def insert(self, table: str, row: dict) -> dict:
        rows = self._request('POST', '/rest/v1/' + table, body=row, prefer='return=representation') or []
        return rows[0] if rows else {}

    def update(self, table: str, filters: dict, changes: dict) -> list[dict]:
        return self._request('PATCH', '/rest/v1/' + table, params=filters, body=changes,
                             prefer='return=representation') or []

    def profiles(self) -> dict[str, dict]:
        """Website profiles (display name, plan chosen at sign-up). Optional table."""
        try:
            rows = self.select('profiles', select='id,display_name,plan', limit=5000)
        except AdminError:
            return {}
        return {r['id']: r for r in rows if isinstance(r, dict) and r.get('id')}


# ------------------------------------------------------------------ admin operations
def _user_state(user: dict) -> str:
    banned = user.get('banned_until')
    if banned:
        try:
            if dt.datetime.fromisoformat(banned.replace('Z', '+00:00')) > _now():
                return 'заблокирован'
        except ValueError:
            return 'заблокирован'
    if not (user.get('email_confirmed_at') or user.get('confirmed_at')):
        return 'не подтверждён'
    return 'активен'


def _short(moment: str | None) -> str:
    if not moment:
        return '—'
    try:
        value = dt.datetime.fromisoformat(moment.replace('Z', '+00:00')).astimezone()
        return value.strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return moment[:16]


def active_plan(subscriptions: list[dict], now: dt.datetime | None = None) -> tuple[str, dict | None]:
    """Highest active plan among a user's subscriptions ('start', None when nothing active)."""
    now = now or _now()
    best, best_row = 'start', None
    for row in subscriptions:
        if row.get('status') != 'active':
            continue
        starts = dt.datetime.fromisoformat(str(row.get('starts_at')).replace('Z', '+00:00')) if row.get('starts_at') else now
        ends = dt.datetime.fromisoformat(str(row['ends_at']).replace('Z', '+00:00')) if row.get('ends_at') else None
        if starts > now or (ends is not None and ends <= now):
            continue
        if best_row is None or PLAN_ORDER.index(row['plan']) > PLAN_ORDER.index(best):
            best, best_row = row['plan'], row
    return best, best_row


def local_usage(db_path=None) -> dict[str, dict]:
    """Per-account message counts from the host's own database (no message text is read)."""
    if db_path is None:
        import core
        db_path = core.DB_PATH
    today = dt.date.today().isoformat()
    usage = {}
    try:
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5) as conn:
            for username, total, last, today_count in conn.execute(
                    "SELECT username, COUNT(*), MAX(created), SUM(CASE WHEN role='user' AND created >= ? THEN 1 ELSE 0 END) "
                    "FROM messages WHERE username LIKE 'sb:%' GROUP BY username", (today,)):
                usage[username[3:]] = {'messages': total, 'last': last, 'today': today_count or 0}
    except sqlite3.Error:
        pass
    return usage


class AdminService:
    """Everything the admin panel does, with the owner check and the audit log in one place."""

    def __init__(self, admin_id: str, client: SupabaseAdmin | None = None, db_path=None):
        owner = supabase_auth.admin_user_id()
        if not owner or _uuid(admin_id) != _uuid(owner):
            raise AdminError('Доступ только для администратора хоста.')
        self.admin_id = _uuid(admin_id)
        self.sb = client or SupabaseAdmin()
        self.db_path = db_path

    def _audit(self, action: str, target: str | None = None, **details):
        try:
            self.sb.insert('chelsy_admin_audit', {'admin_id': self.admin_id, 'action': action,
                                                   'target_id': target, 'details': details})
        except AdminError:
            pass   # the action itself already succeeded; a missing audit row must not undo it

    # -- read
    def accounts(self, query: str = '') -> list[dict]:
        users = self.sb.all_users()
        subs = self.sb.select('chelsy_subscriptions', select='*', status='eq.active', limit=10000)
        by_user: dict[str, list] = {}
        for row in subs:
            by_user.setdefault(row['user_id'], []).append(row)
        profiles = self.sb.profiles()
        usage = local_usage(self.db_path)
        q = (query or '').strip().casefold()
        rows = []
        for user in users:
            uid = user.get('id', '')
            profile = profiles.get(uid, {})
            name = profile.get('display_name') or (user.get('user_metadata') or {}).get('display_name') or ''
            email = user.get('email', '')
            if q and q not in email.casefold() and q not in name.casefold() and q not in uid:
                continue
            plan, plan_row = active_plan(by_user.get(uid, []))
            use = usage.get(uid, {})
            rows.append({
                'id': uid, 'email': email, 'name': name, 'state': _user_state(user),
                'plan': plan, 'plan_until': (plan_row or {}).get('ends_at'),
                'wanted_plan': profile.get('plan') or '', 'created': user.get('created_at'),
                'last_sign_in': user.get('last_sign_in_at'), 'messages': use.get('messages', 0),
                'today': use.get('today', 0), 'last_activity': use.get('last'),
                'is_admin': uid == self.admin_id,
            })
        rows.sort(key=lambda r: r.get('last_sign_in') or '', reverse=True)
        return rows

    def subscriptions(self, user_id: str | None = None, only_active: bool = False) -> list[dict]:
        params = {'select': '*', 'order': 'created_at.desc', 'limit': 2000}
        if user_id:
            params['user_id'] = 'eq.' + _uuid(user_id)
        if only_active:
            params['status'] = 'eq.active'
        return self.sb.select('chelsy_subscriptions', **params)

    def activity(self, user_id: str | None = None, kind: str = '', limit: int = 200) -> list[dict]:
        params = {'select': '*', 'order': 'created_at.desc', 'limit': max(1, min(1000, int(limit)))}
        if user_id:
            params['user_id'] = 'eq.' + _uuid(user_id)
        if kind:
            params['kind'] = 'eq.' + re.sub(r'[^a-z_\-]', '', kind)[:40]
        return self.sb.select('chelsy_activity', **params)

    def audit_log(self, limit: int = 200) -> list[dict]:
        return self.sb.select('chelsy_admin_audit', select='*', order='created_at.desc', limit=max(1, min(1000, int(limit))))

    # -- write
    def grant(self, user_id: str, plan: str, days: int | None, note: str = '') -> dict:
        uid = _uuid(user_id)
        if plan not in PLANS:
            raise AdminError('Неизвестный тариф.')
        if days is not None and not (1 <= int(days) <= 3650):
            raise AdminError('Срок подписки — от 1 до 3650 дней или бессрочно.')
        start = _now()
        row = {'user_id': uid, 'plan': plan, 'status': 'active', 'starts_at': _iso(start),
               'ends_at': _iso(start + dt.timedelta(days=int(days))) if days else None,
               'granted_by': self.admin_id, 'note': (note or '').strip()[:500] or None}
        created = self.sb.insert('chelsy_subscriptions', row)
        self._audit('grant_subscription', uid, plan=plan, days=days, note=row['note'])
        return created

    def revoke(self, subscription_id: int) -> list[dict]:
        sid = int(subscription_id)
        rows = self.sb.update('chelsy_subscriptions', {'id': f'eq.{sid}', 'status': 'eq.active'},
                              {'status': 'revoked', 'revoked_at': _iso(_now())})
        if not rows:
            raise AdminError('Активная подписка с таким номером не найдена.')
        self._audit('revoke_subscription', rows[0].get('user_id'), subscription=sid, plan=rows[0].get('plan'))
        return rows

    def set_blocked(self, user_id: str, blocked: bool, reason: str = '') -> dict:
        uid = _uuid(user_id)
        if uid == self.admin_id and blocked:
            raise AdminError('Нельзя заблокировать собственный аккаунт администратора.')
        result = self.sb.update_user(uid, {'ban_duration': FOREVER_BAN if blocked else 'none'})
        self._audit('block_user' if blocked else 'unblock_user', uid, reason=(reason or '').strip()[:300] or None)
        return result

    def confirm_email(self, user_id: str) -> dict:
        uid = _uuid(user_id)
        result = self.sb.update_user(uid, {'email_confirm': True})
        self._audit('confirm_email', uid)
        return result

    def send_password_reset(self, user_id: str) -> str:
        uid = _uuid(user_id)
        email = self.sb.get_user(uid).get('email')
        if not email:
            raise AdminError('У аккаунта нет email.')
        self.sb.send_recovery(email)
        self._audit('send_password_reset', uid)
        return email


# ------------------------------------------------------------------ host hooks (best effort)
_ACTIVITY_QUEUE: list[dict] = []
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY_WAKE = threading.Event()
_ACTIVITY_THREAD: dict = {'thread': None}


def record_activity(user_id: str, kind: str, detail: str = '', device: str = ''):
    """Queue an activity row (metadata only). Silently does nothing without the secret key."""
    try:
        uid = _uuid(user_id)
    except AdminError:
        return
    row = {'user_id': uid, 'kind': re.sub(r'[^a-z_\-]', '', kind)[:40] or 'other',
           'detail': (detail or '')[:300] or None, 'device': re.sub(r'[^\w\-. ]', '', device or '')[:40] or None,
           'created_at': _iso(_now())}
    with _ACTIVITY_LOCK:
        if len(_ACTIVITY_QUEUE) < 5000:
            _ACTIVITY_QUEUE.append(row)
        if _ACTIVITY_THREAD['thread'] is None or not _ACTIVITY_THREAD['thread'].is_alive():
            _ACTIVITY_THREAD['thread'] = threading.Thread(target=_activity_worker, daemon=True, name='chelsy-activity')
            _ACTIVITY_THREAD['thread'].start()
    _ACTIVITY_WAKE.set()


def _activity_worker():
    client = None
    while True:
        _ACTIVITY_WAKE.wait(30)
        _ACTIVITY_WAKE.clear()
        with _ACTIVITY_LOCK:
            batch, _ACTIVITY_QUEUE[:] = list(_ACTIVITY_QUEUE[:200]), _ACTIVITY_QUEUE[200:]
        if not batch:
            continue
        try:
            client = client or SupabaseAdmin()
            client._request('POST', '/rest/v1/chelsy_activity', body=batch, prefer='return=minimal')
        except AdminError:
            client = None          # no key / no tables / offline: activity is optional, drop the batch
        except Exception as exc:   # never let logging break the host
            print('[Activity]', type(exc).__name__, flush=True)


_PLAN_CACHE: dict[str, tuple[str, float]] = {}


def plan_for_token(token: str, user_id: str, ttl: float = 300) -> str:
    """The user's plan through their OWN token (RPC chelsy_my_plan); 'start' when unknown."""
    cached = _PLAN_CACHE.get(user_id)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    plan = 'start'
    try:
        cfg = supabase_auth.config()
        if cfg:
            req = Request(cfg[0] + '/rest/v1/rpc/chelsy_my_plan', data=b'{}', method='POST',
                          headers={'apikey': cfg[1], 'Authorization': 'Bearer ' + token,
                                   'Content-Type': 'application/json', 'Accept': 'application/json'})
            with build_opener().open(req, timeout=6) as response:
                value = json.loads(response.read() or b'"start"')
                plan = value if value in PLANS else 'start'
    except Exception:
        plan = 'start'
    _PLAN_CACHE[user_id] = (plan, time.monotonic() + ttl)
    return plan


def daily_limit_message(user_id: str, token: str | None, db_path=None) -> str | None:
    """Russian refusal when the plan's daily request limit is used up, else None."""
    limits = load_limits()
    if not limits['enabled'] or not token:
        return None
    plan = plan_for_token(token, user_id)
    limit = limits.get(plan, 0)
    if not limit:
        return None
    used = local_usage(db_path).get(user_id, {}).get('today', 0)
    if used < limit:
        return None
    return (f'Дневной лимит тарифа {PLANS[plan]} исчерпан ({limit} запросов в день). '
            'Лимит обновится завтра; расширить его может администратор.')

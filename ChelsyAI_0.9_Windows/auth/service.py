"""Chelsy AI 0.9.4 own authentication service (ТЗ SEC-02, SEC-04, NET-03, ADM-01, ADM-03, MIG-01).

Storage identity: content of every account is keyed by ``sb:<uuid>`` — the prefix is kept from
0.9.3 (Supabase era) so existing conversations, memory and knowledge stay attached to the same
UUID. New local accounts use the same form.

Tokens are opaque: ``<kind>.<session id>.<secret>``. The Host stores only SHA-256 of a token and
uses HKDF(secret) to unwrap the account's data key for that session (see ``vault``).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import passwords, vault
from .throttle import DEFAULT as THROTTLE, Throttle

ACCESS_TTL = 10 * 60
REFRESH_TTL = 30 * 24 * 3600
ADMIN_IDLE = 15 * 60
CHANGE_TOKEN_TTL = 10 * 60
REQUEST_TTL = 72 * 3600
EMAIL_RE = __import__('re').compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}$')
GENERIC_LOGIN_ERROR = 'Неверный email или пароль.'


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = 'error', **extra):
        super().__init__(message)
        self.message, self.status, self.code, self.extra = message, status, code, extra


@dataclass
class Principal:
    account_id: str
    email: str
    role: str
    session_id: str
    is_admin_session: bool
    dek: bytes | None
    key_version: int

    @property
    def username(self) -> str:          # storage key used by core/knowledge
        return 'sb:' + self.account_id

    def acting(self):
        return vault.acting_as(self.username, self.dek, self.key_version)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec='seconds')


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _norm_email(email: str) -> str:
    email = (email or '').strip()
    if not EMAIL_RE.match(email):
        raise AuthError('Укажи корректный email.', 400, 'invalid_email')
    return email.lower()


def _temp_password() -> str:
    words = ['волна', 'кедр', 'маяк', 'север', 'гроза', 'сокол', 'тайга', 'лагуна', 'комета', 'янтарь', 'ветер', 'утёс']
    return '-'.join(secrets.choice(words) for _ in range(4)) + '-' + str(secrets.randbelow(900) + 100)


class AuthService:
    def __init__(self, db_path=None, throttle: Throttle | None = None, clock=_now):
        if db_path is None:
            import core
            db_path = core.DB_PATH
        self.db_path = Path(db_path)
        self.throttle = throttle or THROTTLE
        self.clock = clock
        self.lock = threading.RLock()
        self._pending: dict[str, dict] = {}       # change/recovery tokens (memory only, short-lived)
        self._load_profile()

    # ------------------------------------------------------------------ infrastructure
    def conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def _load_profile(self):
        try:
            with self.conn() as c:
                rows = dict(c.execute('SELECT key, value FROM security_profile').fetchall())
        except sqlite3.Error:
            rows = {}
        passwords.configure(json.loads(rows['argon2'])) if 'argon2' in rows else passwords.configure(None)
        self.access_ttl = int(rows.get('access_ttl', ACCESS_TTL))
        self.refresh_ttl = int(rows.get('refresh_ttl', REFRESH_TTL))
        self.admin_idle = int(rows.get('admin_idle', ADMIN_IDLE))

    def save_profile(self, **values):
        stamp = _iso(self.clock())
        with self.lock, self.conn() as c:
            for key, value in values.items():
                c.execute('INSERT INTO security_profile(key,value,updated) VALUES(?,?,?) '
                          'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated',
                          (key, value if isinstance(value, str) else json.dumps(value), stamp))
        self._load_profile()

    def audit(self, actor, action, target=None, reason='', result='ok', **details):
        with self.conn() as c:
            c.execute('INSERT INTO admin_audit(actor,action,target,reason,result,details,created) VALUES(?,?,?,?,?,?,?)',
                      (actor, action, target, (reason or '')[:300], result, json.dumps(details, ensure_ascii=False),
                       _iso(self.clock())))

    def _event(self, c, account_id, kind, ok, ip='', device=''):
        c.execute('INSERT INTO auth_events(account_id,kind,ok,ip,device,created) VALUES(?,?,?,?,?,?)',
                  (account_id, kind, 1 if ok else 0, (ip or '')[:64], (device or '')[:80], _iso(self.clock())))

    def _account(self, c, *, account_id=None, email=None):
        if account_id:
            return c.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
        return c.execute('SELECT * FROM accounts WHERE email=?', (email.lower(),)).fetchone()

    def _is_admin(self, c, account_id) -> bool:
        return bool(c.execute('SELECT 1 FROM admin_roster r JOIN accounts a ON a.id=r.account_id '
                              "WHERE r.account_id=? AND a.role='admin' AND a.status='active'", (account_id,)).fetchone())

    # ------------------------------------------------------------------ keys
    def _keys(self, c, account_id):
        return c.execute('SELECT * FROM account_keys WHERE account_id=?', (account_id,)).fetchone()

    def _create_keys(self, c, account_id, password) -> tuple[bytes, str, int]:
        dek, code = vault.new_dek(), vault.new_recovery_code()
        pw_salt, rec_salt = secrets.token_bytes(16), secrets.token_bytes(16)
        aad = account_id.encode()
        old = self._keys(c, account_id)
        version = (old['key_version'] + 1) if old else 1
        if old and old['rec_wrap']:
            c.execute('INSERT OR REPLACE INTO account_keys_retired(account_id,key_version,rec_salt,rec_wrap,retired) '
                      'VALUES(?,?,?,?,?)', (account_id, old['key_version'], old['rec_salt'], old['rec_wrap'], _iso(self.clock())))
        stamp = _iso(self.clock())
        c.execute('INSERT INTO account_keys(account_id,key_version,pw_salt,pw_wrap,rec_salt,rec_wrap,created,updated) '
                  'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET key_version=excluded.key_version, '
                  'pw_salt=excluded.pw_salt, pw_wrap=excluded.pw_wrap, rec_salt=excluded.rec_salt, '
                  'rec_wrap=excluded.rec_wrap, updated=excluded.updated',
                  (account_id, version, pw_salt, vault.wrap(vault.kek_from_secret(password, pw_salt), dek, aad),
                   rec_salt, vault.wrap(vault.kek_from_secret(vault.normalize_recovery_code(code), rec_salt), dek, aad),
                   stamp, stamp))
        return dek, code, version

    def _wrap_password(self, c, account_id, dek, password):
        salt = secrets.token_bytes(16)
        c.execute('UPDATE account_keys SET pw_salt=?, pw_wrap=?, updated=? WHERE account_id=?',
                  (salt, vault.wrap(vault.kek_from_secret(password, salt), dek, account_id.encode()),
                   _iso(self.clock()), account_id))

    def _unlock_password(self, keys, account_id, password) -> bytes | None:
        if not keys or not keys['pw_wrap']:
            return None
        try:
            return vault.unwrap(vault.kek_from_secret(password, keys['pw_salt']), keys['pw_wrap'], account_id.encode())
        except vault.VaultError:
            return None

    # ------------------------------------------------------------------ sessions
    def _issue(self, c, account, dek, key_version, kind, device, ip, family=None) -> dict:
        sid = str(uuid.uuid4())
        access_secret, refresh_secret = secrets.token_bytes(32), secrets.token_bytes(32)
        access = 'a.' + sid + '.' + access_secret.hex()
        refresh = 'r.' + sid + '.' + refresh_secret.hex()
        now = self.clock()
        aad = account['id'].encode()
        is_admin = 1 if self._is_admin(c, account['id']) else 0
        c.execute('INSERT INTO sessions(id,account_id,family,kind,device,ip,created,last_seen,access_hash,access_exp,'
                  'refresh_hash,refresh_exp,is_admin,dek_access,dek_refresh) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (sid, account['id'], family or sid, kind, (device or '')[:80], (ip or '')[:64], _iso(now), _iso(now),
                   _sha(access), _iso(now + timedelta(seconds=self.access_ttl)), _sha(refresh),
                   _iso(now + timedelta(seconds=self.refresh_ttl)), is_admin,
                   vault.wrap(vault.kek_from_token(access_secret, b'access'), dek, aad) if dek else None,
                   vault.wrap(vault.kek_from_token(refresh_secret, b'refresh'), dek, aad) if dek else None))
        c.execute('UPDATE accounts SET last_login=? WHERE id=?', (_iso(now), account['id']))
        return {'access_token': access, 'refresh_token': refresh, 'expires_in': self.access_ttl,
                'refresh_expires_in': self.refresh_ttl, 'session_id': sid, 'key_version': key_version,
                'account': self._public(account, is_admin)}

    @staticmethod
    def _public(account, is_admin=False) -> dict:
        return {'id': account['id'], 'email': account['email'], 'display_name': account['display_name'],
                'locale': account['locale'], 'timezone': account['timezone'],
                'role': 'admin' if is_admin else 'user', 'must_change_password': bool(account['must_change_password'])}

    @staticmethod
    def _split(token: str, kind: str) -> tuple[str, bytes]:
        try:
            prefix, sid, secret = token.split('.')
            if prefix != kind or len(secret) != 64:
                raise ValueError
            return str(uuid.UUID(sid)), bytes.fromhex(secret)
        except (ValueError, AttributeError):
            raise AuthError('Сессия недействительна. Войди снова.', 401, 'invalid_token') from None

    def authenticate(self, access_token: str) -> Principal:
        sid, secret = self._split(access_token or '', 'a')
        now = self.clock()
        with self.conn() as c:
            s = c.execute('SELECT s.*, a.email, a.role, a.status FROM sessions s JOIN accounts a ON a.id=s.account_id '
                          'WHERE s.id=? AND s.access_hash=?', (sid, _sha(access_token))).fetchone()
            if not s or s['revoked_at'] or s['status'] != 'active':
                raise AuthError('Сессия завершена. Войди снова.', 401, 'session_revoked')
            if _parse(s['access_exp']) <= now:
                raise AuthError('Срок доступа истёк — обнови сессию.', 401, 'access_expired')
            if s['is_admin'] and (now - _parse(s['last_seen'])).total_seconds() > self.admin_idle:
                c.execute("UPDATE sessions SET revoked_at=?, revoke_reason='admin-idle' WHERE id=?", (_iso(now), sid))
                c.commit()
                raise AuthError('Административная сессия завершена после 15 минут бездействия.', 401, 'admin_idle')
            if (now - _parse(s['last_seen'])).total_seconds() > 30:
                c.execute('UPDATE sessions SET last_seen=? WHERE id=?', (_iso(now), sid))
            keys = self._keys(c, s['account_id'])
            dek = None
            if s['dek_access']:
                try:
                    dek = vault.unwrap(vault.kek_from_token(secret, b'access'), s['dek_access'], s['account_id'].encode())
                except vault.VaultError:
                    dek = None
            is_admin = bool(s['is_admin']) and self._is_admin(c, s['account_id'])
        return Principal(s['account_id'], s['email'], 'admin' if is_admin else 'user', sid, is_admin, dek,
                         keys['key_version'] if keys else 1)

    def refresh(self, refresh_token: str, ip='', device='') -> dict:
        sid, secret = self._split(refresh_token or '', 'r')
        digest = _sha(refresh_token)
        now = self.clock()
        with self.lock, self.conn() as c:
            reused = c.execute('SELECT family FROM refresh_history WHERE refresh_hash=?', (digest,)).fetchone()
            if reused:
                # A rotated refresh token came back: the token was copied. Revoke the whole family.
                c.execute("UPDATE sessions SET revoked_at=?, revoke_reason='refresh-reuse' WHERE family=? AND revoked_at IS NULL",
                          (_iso(now), reused['family']))
                acc = c.execute('SELECT account_id FROM sessions WHERE family=? LIMIT 1', (reused['family'],)).fetchone()
                self._event(c, acc['account_id'] if acc else None, 'refresh_reuse_detected', False, ip, device)
                c.commit()          # the revocation must survive the error below
                raise AuthError('Сессия отозвана: обнаружено повторное использование токена. Войди снова.', 401, 'refresh_reuse')
            s = c.execute('SELECT * FROM sessions WHERE id=? AND refresh_hash=?', (sid, digest)).fetchone()
            if not s or s['revoked_at'] or _parse(s['refresh_exp']) <= now:
                raise AuthError('Сессия завершена. Войди снова.', 401, 'session_revoked')
            account = self._account(c, account_id=s['account_id'])
            if account['status'] != 'active':
                raise AuthError('Аккаунт заблокирован.', 403, 'blocked')
            dek = None
            if s['dek_refresh']:
                try:
                    dek = vault.unwrap(vault.kek_from_token(secret, b'refresh'), s['dek_refresh'], account['id'].encode())
                except vault.VaultError:
                    dek = None
            c.execute('INSERT INTO refresh_history(refresh_hash,session_id,family,rotated) VALUES(?,?,?,?)',
                      (digest, sid, s['family'], _iso(now)))
            c.execute("UPDATE sessions SET revoked_at=?, revoke_reason='rotated', access_hash=NULL, refresh_hash=NULL, "
                      'dek_access=NULL, dek_refresh=NULL WHERE id=?', (_iso(now), sid))
            keys = self._keys(c, account['id'])
            return self._issue(c, account, dek, keys['key_version'] if keys else 1, s['kind'], device or s['device'],
                               ip or s['ip'], family=s['family'])

    def logout(self, principal: Principal):
        self.revoke_session(principal, principal.session_id, reason='logout')

    def sessions_for(self, principal: Principal) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT id,kind,device,ip,created,last_seen FROM sessions WHERE account_id=? "
                             "AND revoked_at IS NULL ORDER BY last_seen DESC", (principal.account_id,)).fetchall()
        return [{**dict(r), 'current': r['id'] == principal.session_id} for r in rows]

    def revoke_session(self, principal: Principal, session_id: str, reason='user'):
        with self.conn() as c:
            n = c.execute('UPDATE sessions SET revoked_at=?, revoke_reason=?, dek_access=NULL, dek_refresh=NULL '
                          'WHERE id=? AND account_id=? AND revoked_at IS NULL',
                          (_iso(self.clock()), reason, session_id, principal.account_id)).rowcount
        if not n:
            raise AuthError('Сессия не найдена.', 404, 'not_found')

    def _revoke_all(self, c, account_id, reason, keep=None):
        c.execute('UPDATE sessions SET revoked_at=?, revoke_reason=?, dek_access=NULL, dek_refresh=NULL '
                  'WHERE account_id=? AND revoked_at IS NULL AND id IS NOT ?', (_iso(self.clock()), reason, account_id, keep))

    def revoke_all(self, principal: Principal, keep_current=True):
        with self.conn() as c:
            self._revoke_all(c, principal.account_id, 'user-all', principal.session_id if keep_current else None)

    def events_for(self, principal: Principal, limit=100) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute('SELECT kind,ok,ip,device,created FROM auth_events WHERE account_id=? '
                                                'ORDER BY id DESC LIMIT ?', (principal.account_id, int(limit))).fetchall()]

    # ------------------------------------------------------------------ sign-in
    def login(self, email: str, password: str, *, ip='', device='', kind='native') -> dict:
        wait = self.throttle.wait_seconds(email, ip)
        if wait:
            raise AuthError(f'Слишком много попыток. Повтори через {wait} с.', 429, 'throttled', retry_after=wait)
        try:
            norm = _norm_email(email)
        except AuthError:
            passwords.dummy_verify(password)
            self.throttle.failure(email, ip)
            raise AuthError(GENERIC_LOGIN_ERROR, 401, 'invalid_credentials')
        with self.lock, self.conn() as c:
            account = self._account(c, email=norm)
            if not account:
                passwords.dummy_verify(password)
                self.throttle.failure(norm, ip)
                self._event(c, None, 'login', False, ip, device)
                c.commit()
                raise AuthError(GENERIC_LOGIN_ERROR, 401, 'invalid_credentials')
            ok, rehash = passwords.verify(account['pw_hash'], password)
            if not ok:
                self.throttle.failure(norm, ip)
                self._event(c, account['id'], 'login', False, ip, device)
                c.commit()
                raise AuthError(GENERIC_LOGIN_ERROR, 401, 'invalid_credentials')
            self.throttle.success(norm, ip)
            if account['status'] == 'blocked':
                self._event(c, account['id'], 'login_blocked', False, ip, device)
                c.commit()
                raise AuthError('Аккаунт заблокирован администратором.', 403, 'blocked')
            if rehash:
                c.execute('UPDATE accounts SET pw_hash=?, updated=? WHERE id=?',
                          (passwords.hash_password(password), _iso(self.clock()), account['id']))
            too_short = len(password) < passwords.MIN_LENGTH
            if account['must_change_password'] or too_short:
                self._event(c, account['id'], 'login_password_change_required', True, ip, device)
                return {'status': 'password_change_required',
                        'change_token': self._pending_token('change', account['id'], password=password, ip=ip,
                                                            device=device, kind=kind),
                        'reason': 'Задай новый пароль (не меньше 15 символов).' if too_short else
                                  'Первый вход или пароль сброшен администратором: задай свой пароль.'}
            keys = self._keys(c, account['id'])
            recovery_code = None
            if keys is None:
                dek, recovery_code, version = self._create_keys(c, account['id'], password)
            else:
                dek, version = self._unlock_password(keys, account['id'], password), keys['key_version']
                if dek is None:
                    self._event(c, account['id'], 'login_key_recovery_required', True, ip, device)
                    return {'status': 'key_recovery_required',
                            'recovery_token': self._pending_token('recover', account['id'], password=password, ip=ip,
                                                                  device=device, kind=kind),
                            'reason': 'Пароль был сброшен. Введи код восстановления, чтобы открыть прежние данные, '
                                      'или начни с новым ключом (прежние зашифрованные данные останутся закрытыми).'}
            self._event(c, account['id'], 'login', True, ip, device)
            result = {'status': 'ok', **self._issue(c, account, dek, version, kind, device, ip)}
        if recovery_code:
            result['recovery_code'] = recovery_code
        return result

    def _pending_token(self, purpose, account_id, **data) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = self.clock()
            for key in [k for k, v in self._pending.items() if v['exp'] <= now]:
                self._pending.pop(key, None)
            self._pending[_sha(token)] = {'purpose': purpose, 'account_id': account_id,
                                          'exp': now + timedelta(seconds=CHANGE_TOKEN_TTL), **data}
        return token

    def _take_pending(self, token, purpose) -> dict:
        with self.lock:
            item = self._pending.pop(_sha(token or ''), None)
        if not item or item['purpose'] != purpose or item['exp'] <= self.clock():
            raise AuthError('Время на это действие истекло. Войди снова.', 401, 'pending_expired')
        return item

    def complete_password_change(self, change_token: str, new_password: str) -> dict:
        item = self._take_pending(change_token, 'change')
        with self.lock, self.conn() as c:
            account = self._account(c, account_id=item['account_id'])
            passwords.check_policy(new_password, account['email'], account['display_name'])
            if passwords.verify(account['pw_hash'], new_password)[0]:
                raise AuthError('Новый пароль должен отличаться от прежнего.', 400, 'same_password')
            keys = self._keys(c, account['id'])
            dek = self._unlock_password(keys, account['id'], item['password']) if keys else None
            recovery_code = None
            if keys is None or (keys['pw_wrap'] is None and keys['rec_wrap'] is None):
                dek, recovery_code, version = self._create_keys(c, account['id'], new_password)
            elif dek is not None:
                self._wrap_password(c, account['id'], dek, new_password)
                version = keys['key_version']
            else:
                # Reset by an administrator: the old key is closed; the user decides on the next sign-in.
                version = keys['key_version']
            c.execute('UPDATE accounts SET pw_hash=?, pw_changed=?, must_change_password=0, updated=? WHERE id=?',
                      (passwords.hash_password(new_password), _iso(self.clock()), _iso(self.clock()), account['id']))
            self._revoke_all(c, account['id'], 'password-changed')
            self._event(c, account['id'], 'password_changed', True, item['ip'], item['device'])
            account = self._account(c, account_id=account['id'])
            if dek is None:
                return {'status': 'key_recovery_required',
                        'recovery_token': self._pending_token('recover', account['id'], password=new_password,
                                                              ip=item['ip'], device=item['device'], kind=item['kind']),
                        'reason': 'Введи код восстановления, чтобы открыть прежние данные, или начни с новым ключом.'}
            result = {'status': 'ok', **self._issue(c, account, dek, version, item['kind'], item['device'], item['ip'])}
        if recovery_code:
            result['recovery_code'] = recovery_code
        return result

    def recover_keys(self, recovery_token: str, recovery_code: str | None) -> dict:
        """Open the old data key with the user's recovery code, or start a new key (old data stays closed)."""
        item = self._take_pending(recovery_token, 'recover')
        with self.lock, self.conn() as c:
            account = self._account(c, account_id=item['account_id'])
            keys = self._keys(c, account['id'])
            new_code = None
            if recovery_code:
                try:
                    kek = vault.kek_from_secret(vault.normalize_recovery_code(recovery_code), keys['rec_salt'])
                    dek = vault.unwrap(kek, keys['rec_wrap'], account['id'].encode())
                except (vault.VaultError, TypeError):
                    self._event(c, account['id'], 'key_recovery', False, item['ip'], item['device'])
                    c.commit()
                    raise AuthError('Код восстановления не подошёл.', 400, 'bad_recovery_code',
                                    recovery_token=self._pending_token('recover', account['id'], **{
                                        k: item[k] for k in ('password', 'ip', 'device', 'kind')}))
                self._wrap_password(c, account['id'], dek, item['password'])
                version = keys['key_version']
            else:
                dek, new_code, version = self._create_keys(c, account['id'], item['password'])
            self._event(c, account['id'], 'key_recovery' if recovery_code else 'key_new', True, item['ip'], item['device'])
            result = {'status': 'ok', **self._issue(c, account, dek, version, item['kind'], item['device'], item['ip'])}
        if new_code:
            result['recovery_code'] = new_code
        return result

    def change_password(self, principal: Principal, current: str, new: str) -> dict:
        with self.lock, self.conn() as c:
            account = self._account(c, account_id=principal.account_id)
            if not passwords.verify(account['pw_hash'], current)[0]:
                self._event(c, account['id'], 'password_change', False)
                c.commit()
                raise AuthError('Текущий пароль неверен.', 400, 'wrong_password')
            passwords.check_policy(new, account['email'], account['display_name'])
            keys = self._keys(c, account['id'])
            dek = self._unlock_password(keys, account['id'], current) or principal.dek
            if dek is not None and keys is not None:
                self._wrap_password(c, account['id'], dek, new)
            c.execute('UPDATE accounts SET pw_hash=?, pw_changed=?, updated=? WHERE id=?',
                      (passwords.hash_password(new), _iso(self.clock()), _iso(self.clock()), account['id']))
            self._revoke_all(c, account['id'], 'password-changed')
            self._event(c, account['id'], 'password_changed', True)
            sess = c.execute('SELECT kind, device, ip FROM sessions WHERE id=?', (principal.session_id,)).fetchone()
            return {'status': 'ok', **self._issue(c, self._account(c, account_id=account['id']), dek,
                                                  keys['key_version'] if keys else 1, sess['kind'], sess['device'], sess['ip'])}

    def change_email(self, principal: Principal, current_password: str, new_email: str):
        """Owner re-verification by password. Without own mail the new address cannot be confirmed by
        a letter (ТЗ NET-03): the change is applied after the password check and logged."""
        new = _norm_email(new_email)
        with self.lock, self.conn() as c:
            account = self._account(c, account_id=principal.account_id)
            if not passwords.verify(account['pw_hash'], current_password)[0]:
                raise AuthError('Текущий пароль неверен.', 400, 'wrong_password')
            if self._account(c, email=new):
                raise AuthError('Этот email уже используется.', 409, 'email_taken')
            c.execute('UPDATE accounts SET email=?, updated=? WHERE id=?', (new, _iso(self.clock()), account['id']))
            self._revoke_all(c, account['id'], 'email-changed', keep=principal.session_id)
            self._event(c, account['id'], 'email_changed', True)

    def update_profile(self, principal: Principal, *, display_name=None, locale=None, timezone_name=None, settings=None):
        fields, args = [], []
        if display_name is not None:
            fields.append('display_name=?'); args.append(str(display_name).strip()[:80])
        if locale is not None:
            if locale not in ('ru', 'en'):
                raise AuthError('Поддерживаются языки ru и en.', 400, 'invalid_locale')
            fields.append('locale=?'); args.append(locale)
        if timezone_name is not None:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                ZoneInfo(str(timezone_name))
            except (ZoneInfoNotFoundError, ValueError):
                raise AuthError('Неизвестный часовой пояс.', 400, 'invalid_timezone') from None
            fields.append('timezone=?'); args.append(str(timezone_name))
        if settings is not None:
            fields.append('settings=?'); args.append(json.dumps(settings, ensure_ascii=False)[:4000])
        if not fields:
            return self.me(principal)
        with self.conn() as c:
            c.execute(f'UPDATE accounts SET {", ".join(fields)}, updated=? WHERE id=?',
                      (*args, _iso(self.clock()), principal.account_id))
        return self.me(principal)

    def me(self, principal: Principal) -> dict:
        with self.conn() as c:
            account = self._account(c, account_id=principal.account_id)
            return {**self._public(account, principal.role == 'admin'),
                    'quotas': json.loads(account['quotas'] or '{}'), 'settings': json.loads(account['settings'] or '{}'),
                    'created': account['created'], 'last_login': account['last_login'],
                    'has_avatar': account['avatar'] is not None, 'status': account['status']}

    def request_deletion(self, principal: Principal, password: str):
        with self.conn() as c:
            account = self._account(c, account_id=principal.account_id)
            if not passwords.verify(account['pw_hash'], password)[0]:
                raise AuthError('Пароль неверен.', 400, 'wrong_password')
            if self._is_admin(c, account['id']):
                raise AuthError('Администратор не может удалить свой аккаунт, пока он в составе администраторов.', 409, 'admin')
            c.execute("UPDATE accounts SET status='deletion_requested', updated=? WHERE id=?", (_iso(self.clock()), account['id']))
            self._revoke_all(c, account['id'], 'deletion-requested')
            self._event(c, account['id'], 'deletion_requested', True)

    # ------------------------------------------------------------------ account creation & import
    def create_account(self, actor: str, email: str, display_name='', role='user') -> tuple[str, str]:
        """Local creation (no own mail): returns (account id, one-time password the admin hands over)."""
        if role not in ('user', 'admin'):
            raise AuthError('Неизвестная роль.', 400, 'invalid_role')
        norm = _norm_email(email)
        temp = _temp_password()
        stamp = _iso(self.clock())
        account_id = str(uuid.uuid4())
        with self.lock, self.conn() as c:
            if self._account(c, email=norm):
                raise AuthError('Аккаунт с таким email уже есть.', 409, 'email_taken')
            c.execute('INSERT INTO accounts(id,email,display_name,role,pw_hash,pw_changed,must_change_password,created,updated) '
                      'VALUES(?,?,?,?,?,?,1,?,?)', (account_id, norm, str(display_name)[:80], role,
                                                   passwords.hash_password(temp), stamp, stamp, stamp))
        self.audit(actor, 'create_account', account_id, result='ok', role=role)
        return account_id, temp

    def import_account(self, *, account_id, email, pw_hash, display_name='', created=None, last_login=None,
                       blocked=False) -> bool:
        """Supabase migration (MIG-01): same UUID, bcrypt hash verified and upgraded at first sign-in."""
        uid = str(uuid.UUID(str(account_id)))
        norm = _norm_email(email)
        if pw_hash and not str(pw_hash).startswith(('$2a$', '$2b$', '$2y$', '$argon2id$')):
            raise AuthError('Неизвестный формат хеша пароля.', 400, 'bad_hash')
        stamp = _iso(self.clock())
        with self.lock, self.conn() as c:
            if self._account(c, account_id=uid):
                return False
            must_change = 0 if pw_hash else 1
            c.execute('INSERT INTO accounts(id,email,display_name,role,status,pw_hash,pw_changed,must_change_password,'
                      'created,updated,last_login,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                      (uid, norm, str(display_name or '')[:80], 'user', 'blocked' if blocked else 'active',
                       pw_hash or passwords.hash_password(secrets.token_urlsafe(32)), stamp, must_change,
                       created or stamp, stamp, last_login, 'supabase-import'))
        return True

    # ------------------------------------------------------------------ administrators (ADM-01)
    def roster(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute('SELECT r.slot, a.id, a.email, r.since FROM admin_roster r '
                                                'JOIN accounts a ON a.id=r.account_id ORDER BY r.slot').fetchall()]

    def setup_admins_local(self, email1: str, email2: str, *, recovery=False) -> list[tuple[str, str | None]]:
        """Owner-only local procedure (CLI on the Host). First setup, or recovery when both admins are lost.
        Never makes legacy 'owner' or the old admin_user_id an administrator automatically."""
        e1, e2 = _norm_email(email1), _norm_email(email2)
        if e1 == e2:
            raise AuthError('Нужны два разных email: два администратора — это два человека.', 400, 'same_admin')
        created = []
        with self.lock, self.conn() as c:
            existing = c.execute('SELECT COUNT(*) FROM admin_roster').fetchone()[0]
            if existing and not recovery:
                raise AuthError('Администраторы уже назначены. Замена — через двойное подтверждение в панели.', 409, 'roster_exists')
            c.execute("UPDATE accounts SET role='user' WHERE id IN (SELECT account_id FROM admin_roster)")
            c.execute('DELETE FROM admin_roster')
        for slot, email in ((1, e1), (2, e2)):
            with self.conn() as c:
                account = self._account(c, email=email)
            temp = None
            if account is None:
                account_id, temp = self.create_account('owner-local', email, role='admin')
            else:
                account_id = account['id']
            with self.lock, self.conn() as c:
                c.execute("UPDATE accounts SET role='admin', status='active' WHERE id=?", (account_id,))
                c.execute('INSERT INTO admin_roster(slot,account_id,since) VALUES(?,?,?)', (slot, account_id, _iso(self.clock())))
                self._revoke_all(c, account_id, 'role-changed')
            created.append((email, temp))
        self.audit('owner-local', 'admin_recovery' if recovery else 'admin_setup', None,
                   result='ok', admins=[e1, e2])
        return created

    def require_admin(self, principal: Principal):
        if principal.role != 'admin' or not principal.is_admin_session:
            raise AuthError('Действие доступно только администраторам.', 403, 'forbidden')

    def admin_accounts(self, principal: Principal, query='') -> list[dict]:
        """Service fields only (ADM-03): no content, titles, topics or file names."""
        self.require_admin(principal)
        q = '%' + (query or '').strip().lower().replace('%', '').replace('_', '')[:80] + '%'
        with self.conn() as c:
            rows = c.execute(
                "SELECT a.id, a.email, a.display_name, a.role, a.status, a.created, a.last_login, a.quotas, "
                "a.must_change_password, a.origin, "
                "(SELECT COUNT(*) FROM sessions s WHERE s.account_id=a.id AND s.revoked_at IS NULL) AS sessions, "
                "(SELECT MAX(last_seen) FROM sessions s WHERE s.account_id=a.id) AS last_seen "
                "FROM accounts a WHERE lower(a.email) LIKE ? OR lower(a.display_name) LIKE ? OR a.id LIKE ? "
                "ORDER BY a.last_login DESC", (q, q, q)).fetchall()
        return [{**dict(r), 'quotas': json.loads(r['quotas'] or '{}')} for r in rows]

    def _target(self, c, target_id):
        account = self._account(c, account_id=str(uuid.UUID(str(target_id))))
        if not account:
            raise AuthError('Аккаунт не найден.', 404, 'not_found')
        return account

    def admin_set_blocked(self, principal: Principal, target_id: str, blocked: bool, reason: str):
        self.require_admin(principal)
        with self.lock, self.conn() as c:
            target = self._target(c, target_id)
            if self._is_admin(c, target['id']):
                raise AuthError('Администратора нельзя заблокировать: замените его через двойное подтверждение.', 409, 'admin_target')
            c.execute('UPDATE accounts SET status=?, updated=? WHERE id=?',
                      ('blocked' if blocked else 'active', _iso(self.clock()), target['id']))
            if blocked:
                self._revoke_all(c, target['id'], 'blocked-by-admin')
        self.audit(principal.account_id, 'block' if blocked else 'unblock', target['id'], reason)

    def admin_revoke_sessions(self, principal: Principal, target_id: str, reason: str):
        self.require_admin(principal)
        with self.conn() as c:
            target = self._target(c, target_id)
            self._revoke_all(c, target['id'], 'revoked-by-admin')
        self.audit(principal.account_id, 'revoke_sessions', target['id'], reason)

    def admin_reset_password(self, principal: Principal, target_id: str, reason: str) -> str:
        """One-time password for the user. The password wrap of the data key is REMOVED: the admin's
        knowledge of the one-time password does not open old content (only the user's recovery code does)."""
        self.require_admin(principal)
        temp = _temp_password()
        with self.lock, self.conn() as c:
            target = self._target(c, target_id)
            if self._is_admin(c, target['id']) and target['id'] != principal.account_id:
                raise AuthError('Пароль другого администратора сбрасывается только через двойное подтверждение.', 409, 'admin_target')
            c.execute('UPDATE accounts SET pw_hash=?, pw_changed=?, must_change_password=1, updated=? WHERE id=?',
                      (passwords.hash_password(temp), _iso(self.clock()), _iso(self.clock()), target['id']))
            c.execute('UPDATE account_keys SET pw_salt=NULL, pw_wrap=NULL, updated=? WHERE account_id=?',
                      (_iso(self.clock()), target['id']))
            self._revoke_all(c, target['id'], 'password-reset-by-admin')
        self.audit(principal.account_id, 'reset_password', target['id'], reason)
        return temp

    def admin_set_quotas(self, principal: Principal, target_id: str, quotas: dict, reason=''):
        self.require_admin(principal)
        allowed = {'messages_per_day', 'files_per_day', 'storage_mb', 'heavy_tasks'}
        clean = {k: max(0, min(1_000_000, int(v))) for k, v in (quotas or {}).items() if k in allowed}
        with self.conn() as c:
            target = self._target(c, target_id)
            c.execute('UPDATE accounts SET quotas=?, updated=? WHERE id=?', (json.dumps(clean), _iso(self.clock()), target['id']))
        self.audit(principal.account_id, 'set_quotas', target['id'], reason, **clean)

    def admin_create_account(self, principal: Principal, email: str, display_name='') -> tuple[str, str]:
        self.require_admin(principal)
        return self.create_account(principal.account_id, email, display_name, role='user')

    def admin_audit_log(self, principal: Principal, limit=200) -> list[dict]:
        self.require_admin(principal)
        with self.conn() as c:
            return [dict(r) for r in c.execute('SELECT * FROM admin_audit ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()]

    # -- actions that need BOTH administrators (ADM-01, ADM-03)
    def request_joint_action(self, principal: Principal, kind: str, payload: dict, reason: str) -> str:
        self.require_admin(principal)
        if kind not in ('replace_admin', 'delete_accounts'):
            raise AuthError('Неизвестное действие.', 400, 'invalid_kind')
        if kind == 'replace_admin':
            if int(payload.get('slot', 0)) not in (1, 2):
                raise AuthError('Укажи слот администратора 1 или 2.', 400, 'invalid_slot')
            _norm_email(payload.get('email', ''))
        if kind == 'delete_accounts':
            ids = [str(uuid.UUID(str(i))) for i in payload.get('ids', [])][:500]
            if not ids:
                raise AuthError('Список аккаунтов пуст.', 400, 'empty')
            payload = {'ids': ids}
        rid = str(uuid.uuid4())
        now = self.clock()
        with self.conn() as c:
            c.execute('INSERT INTO admin_requests(id,kind,payload,created_by,created,expires) VALUES(?,?,?,?,?,?)',
                      (rid, kind, json.dumps({**payload, 'reason': reason[:300]}), principal.account_id, _iso(now),
                       _iso(now + timedelta(seconds=REQUEST_TTL))))
        self.audit(principal.account_id, 'request_' + kind, None, reason, result='pending', request=rid)
        return rid

    def pending_joint_actions(self, principal: Principal) -> list[dict]:
        self.require_admin(principal)
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM admin_requests WHERE status='pending' ORDER BY created").fetchall()]

    def decide_joint_action(self, principal: Principal, request_id: str, approve: bool):
        self.require_admin(principal)
        with self.lock, self.conn() as c:
            req = c.execute("SELECT * FROM admin_requests WHERE id=? AND status='pending'", (request_id,)).fetchone()
            if not req:
                raise AuthError('Запрос не найден или уже решён.', 404, 'not_found')
            if req['created_by'] == principal.account_id:
                raise AuthError('Подтвердить должен второй администратор.', 403, 'same_admin')
            if _parse(req['expires']) <= self.clock():
                c.execute("UPDATE admin_requests SET status='expired' WHERE id=?", (request_id,))
                c.commit()
                raise AuthError('Срок запроса истёк (72 часа).', 410, 'expired')
            payload = json.loads(req['payload'])
            status = 'rejected'
            if approve:
                if req['kind'] == 'replace_admin':
                    self._replace_admin(c, int(payload['slot']), payload['email'])
                elif req['kind'] == 'delete_accounts':
                    for account_id in payload['ids']:
                        if not self._is_admin(c, account_id):
                            c.execute("UPDATE accounts SET status='deletion_requested', updated=? WHERE id=?",
                                      (_iso(self.clock()), account_id))
                            self._revoke_all(c, account_id, 'deletion-approved')
                status = 'approved'
            c.execute('UPDATE admin_requests SET status=?, decided_by=?, decided=? WHERE id=?',
                      (status, principal.account_id, _iso(self.clock()), request_id))
        self.audit(principal.account_id, ('approve_' if approve else 'reject_') + req['kind'], None,
                   payload.get('reason', ''), result=status, request=request_id)

    def _replace_admin(self, c, slot, email):
        norm = _norm_email(email)
        account = self._account(c, email=norm)
        if account is None:
            raise AuthError('Сначала создайте аккаунт нового администратора.', 409, 'no_account')
        old = c.execute('SELECT account_id FROM admin_roster WHERE slot=?', (slot,)).fetchone()
        if old:
            c.execute("UPDATE accounts SET role='user' WHERE id=?", (old['account_id'],))
            self._revoke_all(c, old['account_id'], 'role-changed')
        c.execute('DELETE FROM admin_roster WHERE slot=? OR account_id=?', (slot, account['id']))
        c.execute("UPDATE accounts SET role='admin', status='active' WHERE id=?", (account['id'],))
        c.execute('INSERT INTO admin_roster(slot,account_id,since) VALUES(?,?,?)', (slot, account['id'], _iso(self.clock())))
        self._revoke_all(c, account['id'], 'role-changed')

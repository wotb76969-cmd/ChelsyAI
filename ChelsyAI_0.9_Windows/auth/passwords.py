"""Password policy and hashing (ТЗ SEC-02, NIST SP 800-63B-4 password-only profile AAL1).

* Length 15..128 characters (≥64 supported), any characters, paste allowed, no composition rules,
  no calendar rotation.
* Local blocklist of known weak passwords (SecLists, MIT) plus context checks (email, name,
  repetition, sequences). The password is never sent to an external service.
* New hashes: Argon2id with a per-hash salt; parameters measured on the Host (``measure``)
  and stored in the security profile. Imported Supabase hashes (bcrypt) are verified and
  replaced by Argon2id on the next successful sign-in.
* Concurrency of hash checks is limited to protect the Host from overload.
"""
from __future__ import annotations

import gzip
import json
import re
import threading
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

import bcrypt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 15
MAX_LENGTH = 128
DEFAULT_PARAMS = {'time_cost': 3, 'memory_cost': 65536, 'parallelism': 2}   # 64 MiB, measured on the Host later
_CHECKS = threading.BoundedSemaphore(4)          # at most 4 concurrent password checks
_SEQUENCES = ('abcdefghijklmnopqrstuvwxyz', '01234567890', 'qwertyuiopasdfghjklzxcvbnm',
              'йцукенгшщзхъфывапролджэячсмитьбю', 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя')


class PasswordPolicyError(ValueError):
    """Russian, user-facing list of reasons."""

    def __init__(self, reasons):
        super().__init__(' '.join(reasons))
        self.reasons = reasons


def _normalize(password: str) -> str:
    # NIST: apply Unicode normalisation so the same password typed on different devices matches.
    return unicodedata.normalize('NFKC', password)


@lru_cache(maxsize=1)
def _blocklist() -> frozenset:
    path = Path(__file__).with_name('weak_passwords.txt.gz')
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            return frozenset(line.strip() for line in handle if line.strip())
    except OSError:
        return frozenset()


def _is_sequence_or_repeat(value: str) -> bool:
    """Few distinct characters, a repeated unit ("abcabcabc…") or mostly keyboard/alphabet runs."""
    low = re.sub(r'\s+', '', value.casefold())
    if len(set(low)) <= 4:
        return True
    for unit in range(1, len(low) // 2 + 1):
        if len(low) % unit == 0 and low[:unit] * (len(low) // unit) == low:
            return True
    windows = [low[i:i + 4] for i in range(len(low) - 3)]
    in_runs = sum(1 for w in windows if any(w in seq or w in seq[::-1] for seq in _SEQUENCES))
    return bool(windows) and in_runs / len(windows) >= 0.7


def check_policy(password: str, email: str = '', display_name: str = '') -> None:
    """Raise PasswordPolicyError with Russian reasons when the password is not acceptable."""
    if not isinstance(password, str):
        raise PasswordPolicyError(['Пароль должен быть строкой.'])
    value = _normalize(password)
    reasons = []
    if len(value) < MIN_LENGTH:
        reasons.append(f'Пароль должен содержать не меньше {MIN_LENGTH} символов (сейчас {len(value)}).')
    if len(value) > MAX_LENGTH:
        reasons.append(f'Пароль не длиннее {MAX_LENGTH} символов.')
    low = value.casefold()
    squeezed = re.sub(r'[\W_]+', '', low)
    trimmed = re.sub(r'\d+$', '', squeezed)            # "sunshinesunshine2024" -> "sunshinesunshine"
    if low in _blocklist() or squeezed in _blocklist() or (len(squeezed) < 20 and trimmed in _blocklist()):
        reasons.append('Этот пароль есть в списках часто используемых — выбери другой.')
    elif _is_sequence_or_repeat(value):
        reasons.append('Пароль состоит из повторов или последовательности символов.')
    local = (email or '').split('@')[0].casefold()
    if len(local) >= 4 and local in low:
        reasons.append('Пароль не должен содержать email.')
    name = (display_name or '').casefold().strip()
    if len(name) >= 4 and name in low:
        reasons.append('Пароль не должен содержать имя.')
    if any(w in low for w in ('chelsy', 'челси')) and len(squeezed) < 20:
        reasons.append('Пароль не должен строиться на названии сервиса.')
    if reasons:
        raise PasswordPolicyError(reasons)


# ------------------------------------------------------------------ hashing
_PARAMS = {'value': dict(DEFAULT_PARAMS)}


def configure(params: dict | None) -> dict:
    """Use measured Argon2id parameters (from the security profile)."""
    clean = dict(DEFAULT_PARAMS)
    for key in clean:
        if params and isinstance(params.get(key), int) and params[key] > 0:
            clean[key] = params[key]
    clean['memory_cost'] = max(19456, clean['memory_cost'])     # OWASP minimum for Argon2id: 19 MiB
    clean['time_cost'] = max(2, clean['time_cost'])
    _PARAMS['value'] = clean
    return clean


def _hasher() -> PasswordHasher:
    p = _PARAMS['value']
    return PasswordHasher(time_cost=p['time_cost'], memory_cost=p['memory_cost'], parallelism=p['parallelism'],
                          hash_len=32, salt_len=16, type=Type.ID)


def hash_password(password: str) -> str:
    with _CHECKS:
        return _hasher().hash(_normalize(password))


def verify(stored: str, password: str) -> tuple[bool, bool]:
    """(matches, needs_rehash). Supports Argon2id and imported bcrypt ($2a$/$2b$/$2y$)."""
    if not isinstance(password, str) or not stored or len(password) > 4 * MAX_LENGTH:
        return False, False
    value = _normalize(password)
    with _CHECKS:
        if stored.startswith('$argon2'):
            try:
                _hasher().verify(stored, value)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False, False
            return True, _hasher().check_needs_rehash(stored)
        if stored.startswith(('$2a$', '$2b$', '$2y$')):
            try:
                ok = bcrypt.checkpw(value.encode('utf-8')[:72], stored.replace('$2y$', '$2b$', 1).encode('ascii'))
            except ValueError:
                return False, False
            return ok, ok          # always move imported bcrypt hashes to Argon2id
    return False, False


def dummy_verify(password: str) -> None:
    """Spend the same time when the account does not exist (no email enumeration by timing)."""
    verify(_dummy_hash(), password or 'x')


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher().hash('chelsy-timing-equaliser-' + str(time.time()))


def measure(target_ms: float = 400.0, max_memory_kib: int = 262144) -> dict:
    """Pick Argon2id parameters for this machine: as much memory as fits ~target_ms, time_cost ≥ 2."""
    best = dict(DEFAULT_PARAMS)
    memory = 19456
    while memory <= max_memory_kib:
        hasher = PasswordHasher(time_cost=2, memory_cost=memory, parallelism=2, type=Type.ID)
        started = time.perf_counter()
        hasher.hash('measure-only')
        elapsed = (time.perf_counter() - started) * 1000
        if elapsed > target_ms:
            break
        best = {'time_cost': 2, 'memory_cost': memory, 'parallelism': 2, 'measured_ms': round(elapsed, 1)}
        memory *= 2
    return best


def profile_json() -> str:
    return json.dumps(_PARAMS['value'])

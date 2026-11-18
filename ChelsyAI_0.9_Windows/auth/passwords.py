"""Argon2id password hashing and local weak-password checks (SEC-02)."""
from __future__ import annotations

import hashlib
import secrets
import threading
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, InvalidHashError

# Measured defaults for a typical Host laptop; owner may tune via env later.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_VERIFY_SEM = threading.BoundedSemaphore(2)  # limit parallel verifies (DoS)

MIN_LEN = 15
MAX_LEN = 128


class PasswordError(ValueError):
    pass


def _weak_set() -> set[str]:
    """Local common-password denylist (never sent off-host)."""
    path = Path(__file__).with_name('common_passwords.txt')
    words = {
        'password', 'password12345', 'qwertyuiopasdf', 'chelseyai123456',
        '123456789012345', 'adminadminadmin', 'letmeinletmein1',
    }
    if path.is_file():
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                w = line.strip()
                if w and not w.startswith('#'):
                    words.add(w.lower())
        except OSError:
            pass
    return words


_WEAK = None


def validate_password_policy(password: str) -> None:
    if not isinstance(password, str):
        raise PasswordError('Пароль обязателен')
    if len(password) < MIN_LEN:
        raise PasswordError(f'Пароль должен содержать не менее {MIN_LEN} символов')
    if len(password) > MAX_LEN:
        raise PasswordError(f'Пароль не длиннее {MAX_LEN} символов')
    global _WEAK
    if _WEAK is None:
        _WEAK = _weak_set()
    if password.lower() in _WEAK:
        raise PasswordError('Пароль слишком простой — выберите другой')
    # Reject if entropy-ish: all same char / pure digits under 20
    if len(set(password)) < 4:
        raise PasswordError('Пароль слишком простой')


def hash_password(password: str) -> str:
    validate_password_policy(password)
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    if not password_hash or not isinstance(password, str):
        return False
    with _VERIFY_SEM:
        try:
            if password_hash.startswith(('$2a$','$2b$','$2y$')):
                import bcrypt
                raw=password.encode('utf-8')
                return len(raw)<=72 and bcrypt.checkpw(raw,password_hash.encode('ascii'))
            return _HASHER.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError, TypeError, ValueError):
            return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _HASHER.check_needs_rehash(password_hash)
    except Exception:
        return True


def digest_for_log(value: str) -> str:
    """Non-reversible fingerprint for diagnostics — never the secret itself."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)

"""Per-user content keys (AES-256-GCM). Admins do NOT hold user recovery secrets (SEC-04)."""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def _unb64(text: str) -> bytes:
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def generate_user_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def wrap_user_key(user_key: bytes, password: str, *, salt: bytes | None = None) -> dict:
    """Encrypt the user content key with a key derived from the user's password.

    Admins cannot unwrap without the password. Lost password ⇒ account can be
    reset, but old ciphertext is not recoverable unless the user kept a backup code.
    """
    salt = salt or secrets.token_bytes(16)
    # HKDF over a password-derived material (Argon2 already used for login hash;
    # here we use a separate HKDF+SHA256 of password+salt for key wrapping only).
    material = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000, dklen=32)
    aes = AESGCM(material)
    nonce = secrets.token_bytes(12)
    wrapped = aes.encrypt(nonce, user_key, b'chelsy-user-key-v1')
    return {
        'alg': 'AES-256-GCM',
        'kdf': 'PBKDF2-SHA256-200k',
        'salt': _b64(salt),
        'nonce': _b64(nonce),
        'wrapped': _b64(wrapped),
    }


def unwrap_user_key(blob: dict, password: str) -> bytes:
    salt = _unb64(blob['salt'])
    nonce = _unb64(blob['nonce'])
    wrapped = _unb64(blob['wrapped'])
    material = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000, dklen=32)
    aes = AESGCM(material)
    return aes.decrypt(nonce, wrapped, b'chelsy-user-key-v1')


def encrypt_bytes(user_key: bytes, plaintext: bytes, aad: bytes = b'') -> dict:
    nonce = secrets.token_bytes(12)
    aes = AESGCM(user_key)
    ct = aes.encrypt(nonce, plaintext, aad)
    return {'nonce': _b64(nonce), 'ciphertext': _b64(ct)}


def decrypt_bytes(user_key: bytes, blob: dict, aad: bytes = b'') -> bytes:
    aes = AESGCM(user_key)
    return aes.decrypt(_unb64(blob['nonce']), _unb64(blob['ciphertext']), aad)


def host_master_key() -> bytes:
    """Host-local master for server-side envelopes (NOT an admin escrow for user data).

    Used only for Host-at-rest protection of operational secrets. Per SEC-04 this
    must never be documented as end-to-end encryption against the Host operator.
    """
    raw = os.environ.get('CHELSY_HOST_MASTER_KEY', '').strip()
    if raw:
        return hashlib.sha256(raw.encode('utf-8')).digest()
    path = os.environ.get('CHELSY_HOST_MASTER_KEY_FILE', '')
    if path and os.path.isfile(path):
        return hashlib.sha256(Path_read(path)).digest()
    # Ephemeral fallback for tests — production must set CHELSY_HOST_MASTER_KEY
    raise RuntimeError('Настройте локальный ключ Host для этого действия.')


def Path_read(path: str) -> bytes:
    with open(path, 'rb') as f:
        return f.read()


def derive_scope_key(user_key: bytes, scope: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f'chelsy-scope:{scope}'.encode('utf-8'),
    ).derive(user_key)

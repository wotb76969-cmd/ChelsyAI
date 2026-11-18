"""A token can open only its own user's content key, even after Host restart."""
import hashlib
import json
from .crypto_keys import decrypt_bytes, encrypt_bytes, unwrap_user_key


def binding(token):
    return hashlib.sha256(b'chelsy-vault-v1\0' + token.encode('ascii')).digest()


def unlock(conn, uid, password):
    row = conn.execute('SELECT key_wrap_json FROM auth_users WHERE id=?',(uid,)).fetchone()
    return unwrap_user_key(json.loads(row[0]), password)


def bind(conn, tokens, uid, key):
    envelopes = [json.dumps(encrypt_bytes(binding(tokens[name]), key, uid.encode())) for name in ('access_token','refresh_token')]
    conn.execute('INSERT OR REPLACE INTO vault_sessions(session_id, access_box, refresh_box) VALUES(?,?,?)',
                 (tokens['session_id'], *envelopes))


def recover(conn, sid, uid, token, *, refresh=False):
    row = conn.execute('SELECT access_box,refresh_box FROM vault_sessions WHERE session_id=?',(sid,)).fetchone()
    if row is None:
        raise ValueError('login_required')
    return decrypt_bytes(binding(token), json.loads(row[1 if refresh else 0]), uid.encode())


def seal(key, obj, context):
    return json.dumps(encrypt_bytes(key, json.dumps(obj,ensure_ascii=False).encode(), context.encode()))


def open_json(key, box, context):
    return json.loads(decrypt_bytes(key,json.loads(box),context.encode()))

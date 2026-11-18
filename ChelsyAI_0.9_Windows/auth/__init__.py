"""Chelsy AI 0.9.4 — собственная аутентификация (без Supabase).

Пароли: Argon2id. Сессии: opaque access/refresh токены в БД Host.
Администраторы приложения не имеют доступа к частному содержимому (SEC-04).
"""
from .passwords import hash_password, verify_password, validate_password_policy, PasswordError
from .accounts import (
    AuthError,
    create_user,
    authenticate_user,
    get_user,
    list_users_admin,
    set_user_status,
    is_admin,
    change_password,
    change_email,
    storage_key_for,
    update_profile,
)
from .sessions import (
    create_session,
    refresh_session,
    revoke_session,
    revoke_all_sessions,
    resolve_access_token,
    list_sessions,
)

__all__ = [
    'AuthError', 'PasswordError',
    'hash_password', 'verify_password', 'validate_password_policy',
    'create_user', 'authenticate_user', 'get_user', 'list_users_admin',
    'set_user_status', 'ensure_bootstrap_admins', 'is_admin',
    'change_password', 'change_email', 'storage_key_for', 'update_profile',
    'create_session', 'refresh_session', 'revoke_session',
    'revoke_all_sessions', 'resolve_access_token', 'list_sessions',
]

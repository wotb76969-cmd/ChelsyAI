"""Windows Client own-Auth against Chelsy Host api/v3 (0.9.4)."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler


class AuthError(Exception):
    pass


def _call(host: str, path: str, body: dict | None = None, bearer: str | None = None, timeout: int = 20) -> dict:
    host = host.rstrip('/')
    data = None if body is None else json.dumps(body).encode('utf-8')
    headers = {'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    req = Request(host + path, data=data, headers=headers, method='POST' if data is not None else 'GET')
    try:
        with build_opener(HTTPSHandler()).open(req, timeout=timeout) as resp:
            return json.load(resp)
    except HTTPError as exc:
        try:
            payload = json.load(exc)
            msg = payload.get('message') or payload.get('error') or f'HTTP {exc.code}'
        except Exception:
            msg = f'HTTP {exc.code}'
        raise AuthError(str(msg)) from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise AuthError('Host недоступен или неверный ответ Auth') from exc


def login(host: str, email: str, password: str, device_label: str = 'windows-client') -> dict:
    if not email or not password:
        raise AuthError('Email и пароль обязательны')
    result = _call(host, '/api/v3/auth/login', {
        'email': email.strip(), 'password': password, 'device_label': device_label,
    })
    if not result.get('access_token') or not result.get('user', {}).get('id'):
        raise AuthError('Нет активной сессии')
    return result


def refresh(host: str, refresh_token: str) -> dict:
    return _call(host, '/api/v3/auth/refresh', {'refresh_token': refresh_token})


def logout(host: str, access_token: str) -> None:
    try:
        _call(host, '/api/v3/auth/logout', {}, bearer=access_token)
    except AuthError:
        pass

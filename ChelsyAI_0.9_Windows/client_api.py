"""HTTP client for Chelsy Host (no GUI dependencies; used by the Windows client and tests)."""
from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener


class HostError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Unauthorized(HostError):
    pass


def validate_host(host):
    host = (host or '').strip().rstrip('/')
    u = urlsplit(host)
    if u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
        raise ValueError('Укажи только адрес хоста, без пути, логина и параметров.')
    if u.scheme == 'https' and u.hostname:
        try:
            ipaddress.ip_address(u.hostname)
        except ValueError:
            return host
        raise ValueError('Укажи имя хоста из Tailscale (https://имя-пк.tailnet.ts.net), а не IP-адрес 100.x.x.x: '
                         'HTTPS-сертификат Tailscale выдаётся только на имя.')
    if host in ('http://127.0.0.1:8787', 'http://localhost:8787'):
        return host  # same-PC test only
    raise ValueError('Используй HTTPS-адрес Tailscale Serve (https://имя.tailnet.ts.net). HTTP разрешён только для localhost.')


def explain_network_error(exc, base=''):
    """Turn a low-level connection failure into a concrete Russian hint."""
    reason = getattr(exc, 'reason', exc)
    name = urlsplit(base).hostname or 'хост'
    if isinstance(reason, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(reason):
        return (f'Сертификат {name} не прошёл проверку. Адрес должен быть именем из Tailscale Serve '
                '(https://имя-пк.tailnet.ts.net); в админке Tailscale (DNS) должны быть включены MagicDNS и HTTPS Certificates.')
    if isinstance(reason, ssl.SSLError):
        return f'Ошибка защищённого соединения с {name}: {reason}. Проверь, что на хосте включён доступ (tailscale serve).'
    if isinstance(reason, socket.gaierror):
        return (f'Адрес {name} не найден. На ЭТОМ компьютере Tailscale выключен или вошёл в другой аккаунт, '
                'либо в адресе опечатка. Включи Tailscale (Connected) тем же аккаунтом, что и на хосте.')
    if isinstance(reason, ConnectionRefusedError):
        return ('Компьютер-хост найден, но доступ для устройств на нём не включён. На хосте запусти '
                '«Chelsy AI Host — включить доступ с устройств (Tailscale)» или: tailscale serve --bg 8787.')
    if isinstance(reason, (TimeoutError, socket.timeout)) or 'timed out' in str(reason):
        return ('Хост не отвечает: компьютер выключен или спит, или Tailscale на нём отключён. '
                'Проверь, что ноутбук включён и в Tailscale он «Connected».')
    if isinstance(reason, ConnectionResetError):
        return 'Хост разорвал соединение. Проверь, что Chelsy AI Host запущен, и попробуй ещё раз.'
    return f'Хост недоступен ({reason}). Проверь Tailscale на обоих компьютерах, адрес и запущен ли Chelsy AI Host.'


def explain_http_status(code):
    if code in (502, 503, 504):
        return ('Tailscale на хосте работает, но Chelsy AI Host не запущен или ещё загружается '
                f'(HTTP {code}). Запусти «Chelsy AI Host» на компьютере с нейросетью.')
    return None


class HostClient:
    def __init__(self, base, token_provider, timeout=200):
        self.base = validate_host(base)
        self.token_provider = token_provider        # callable(refresh=False) -> access token
        self.timeout = timeout
        # Never send private credentials through a system proxy.
        self.opener = build_opener(ProxyHandler({}))

    def _request(self, method, path, payload=None, refresh=False):
        token = self.token_provider(refresh)
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json, application/x-ndjson'}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        return Request(self.base + path, data=data, headers=headers, method=method)

    def _open(self, method, path, payload=None):
        for attempt in (False, True):
            try:
                return self.opener.open(self._request(method, path, payload, refresh=attempt), timeout=self.timeout)
            except HTTPError as exc:
                if exc.code == 401 and not attempt:
                    continue          # refresh the access token once
                try:
                    detail = json.load(exc)
                    message = detail.get('message') or detail.get('error') or f'HTTP {exc.code}'
                except Exception:
                    message = f'HTTP {exc.code}'
                if exc.code == 401:
                    raise Unauthorized('Сессия истекла — войди снова.', 401) from exc
                raise HostError(explain_http_status(exc.code) or message, exc.code) from exc
            except (URLError, OSError) as exc:
                raise HostError(explain_network_error(exc, self.base)) from exc
        raise Unauthorized('Сессия истекла — войди снова.', 401)

    def call(self, method, path, payload=None):
        with self._open(method, path, payload) as resp:
            body = resp.read()
        return json.loads(body) if body else {}

    # ------------------------------------------------------------ endpoints
    def health(self):
        try:
            with self.opener.open(self.base + '/api/health', timeout=8) as resp:
                return json.load(resp)
        except HTTPError as exc:
            raise HostError(explain_http_status(exc.code) or f'Хост ответил HTTP {exc.code}.', exc.code) from exc
        except (URLError, OSError) as exc:
            raise HostError(explain_network_error(exc, self.base)) from exc
        except ValueError as exc:
            raise HostError('По этому адресу отвечает не Chelsy AI Host. Проверь адрес.') from exc

    def status(self):
        return self.call('GET', '/api/v2/status')

    def conversations(self, query='', favorites=False):
        params = {'q': query} if query else {}
        if favorites:
            params['favorites'] = '1'
        return self.call('GET', '/api/v2/conversations' + ('?' + urlencode(params) if params else ''))['conversations']

    def messages(self, cid):
        return self.call('GET', f'/api/v2/conversations/{quote(cid)}/messages')['messages']

    def create_conversation(self, title='Новый чат'):
        return self.call('POST', '/api/v2/conversations', {'title': title})['id']

    def update_conversation(self, cid, **fields):
        return self.call('POST', f'/api/v2/conversations/{quote(cid)}', fields)

    def delete_conversation(self, cid):
        return self.call('DELETE', f'/api/v2/conversations/{quote(cid)}')

    def rate(self, message_id, rating):
        return self.call('POST', f'/api/v2/messages/{int(message_id)}/rating', {'rating': rating})

    def stop(self, request_id):
        return self.call('POST', '/api/v2/chat/stop', {'request_id': request_id})

    def chat_stream(self, message, conversation_id=None, model=None, web=True, attachments=None,
                    regenerate=False, edit_message_id=None, request_id=None):
        """Yield NDJSON events from the host: start, status, delta, sources, replace, done, error."""
        payload = {'message': message, 'conversation_id': conversation_id, 'model': model, 'web': web,
                   'attachments': attachments or [], 'stream': True,
                   'request_id': request_id or str(uuid.uuid4())}
        if regenerate:
            payload['regenerate'] = True
        if edit_message_id is not None:
            payload['edit_message_id'] = edit_message_id
        with self._open('POST', '/api/v2/chat', payload) as resp:
            ctype = resp.headers.get('Content-Type', '')
            if 'ndjson' not in ctype:
                yield {'type': 'done', **json.loads(resp.read() or b'{}')}
                return
            for raw in resp:
                line = raw.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue

    def research(self):
        return self.call('GET', '/api/v2/research')['jobs']

    def start_research(self, topic, max_pages=8, scope='personal'):
        return self.call('POST', '/api/v2/research', {'topic': topic, 'max_pages': max_pages, 'scope': scope})['id']

    def research_job(self, job_id):
        return self.call('GET', f'/api/v2/research/{quote(job_id)}')

    def stop_research(self, job_id):
        return self.call('POST', f'/api/v2/research/{quote(job_id)}/stop', {'stop': True})

    def review_item(self, item_id, action, scope='personal'):
        return self.call('POST', f'/api/v2/research/items/{int(item_id)}', {'action': action, 'scope': scope})

    def knowledge(self, query=''):
        return self.call('GET', '/api/v2/knowledge' + ('?' + urlencode({'q': query}) if query else ''))

    def learning(self, limit=50):
        """Autonomous learning journal + host settings."""
        return self.call('GET', f'/api/v2/learning?limit={int(limit)}')

    def save_learning_settings(self, **values):
        return self.call('POST', '/api/v2/learning/settings', values)

    def sync(self):
        return self.call('GET', '/api/v2/sync')

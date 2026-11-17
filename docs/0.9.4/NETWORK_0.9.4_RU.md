# Прямое HTTPS-подключение Host (NET-02)

## Основной вариант

1. Host слушает локальный порт (по умолчанию `127.0.0.1:8787`).
2. Владелец ставит reverse-proxy (Caddy/Nginx) с доверенным сертификатом на свой домен/IP.
3. Клиенты указывают `https://ваш-хост` — без VPN и без Tailscale.

## Переменные

| Переменная | Назначение |
|---|---|
| `CHELSY_HOST_PORT` | порт API |
| `CHELSY_HOST_BIND` | адрес bind (`127.0.0.1` по умолчанию) |
| `CHELSY_ALLOW_PUBLIC_BIND=1` | разрешить не-loopback bind |
| `CHELSY_CORS_ORIGIN` | origin кабинета, если не same-origin |
| `CHELSY_COOKIE_SECURE=1` | Secure-флаг cookie |
| `CHELSY_AUTH_MODE=own` | собственный Auth (по умолчанию) |

## CGNAT

Если у провайдера CGNAT и нет входящего IPv4/IPv6, прямая схема невозможна без смены сети/адреса. Установщик/доктор должен честно сообщать причину. **Скрытый туннель SaaS запрещён ТЗ.**

## Что не открывать наружу

Ollama, SQLite, каталог artifacts, локальную admin panel.

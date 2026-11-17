# Архитектура 0.9.4

## Топология (NET-01)

```
Windows / Android / iOS / Web-кабинет
        │  HTTPS (свой адрес Host)
        ▼
 Chel sy Host (api/v3 own Auth + api/v2 legacy)
        │
        ├─ SQLite (user areas) + artifacts/
        ├─ Ollama 127.0.0.1 (не наружу)
        ├─ Chelsy Mind (router, generators)
        └─ Admin Panel (локально; remote off by default)
```

Продуктивный путь **не** зависит от Tailscale, Supabase, ngrok, Cloudflare Tunnel, внешнего AI API.

## Auth

- Email + пароль (мин. 15). Argon2id.
- Access ~10 мин, refresh ≤30 дней с ротацией.
- Два администратора (`CHELSY_ADMIN_EMAILS`, `CHELSY_ADMIN_PASSWORD` при bootstrap).
- Пользовательский content key обёрнут паролем пользователя (не escrow админа).

## Миграция с 0.9.3 (MIG-01/02)

1. Бэкап SQLite + конфигов.
2. `migrations.py migrate` → v5/v6.
3. Назначить двух админов заново (legacy owner/Supabase UUID не авто-promote).
4. Пароли Supabase: если хеши недоступны — процедура нового пароля без потери UUID (маппинг `auth_legacy_map`).
5. Клиенты обновить до 0.9.4 (старый бинарь с Supabase/Tailscale не обещается).
6. Отключить Supabase после проверенного переноса.

## Сеть

- `CHELSY_HOST_BIND` + `CHELSY_ALLOW_PUBLIC_BIND=1` только после TLS reverse-proxy.
- Диагностика CGNAT — в `NETWORK_0.9.4_RU.md`.

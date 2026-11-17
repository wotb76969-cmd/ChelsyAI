# ChelsyAI

**Chelsy AI 0.9.4** — персональный ИИ-помощник Chelsy Group. Нейросеть и данные на вашем Host; клиенты Windows / Android / кабинет сайта подключаются по **собственному HTTPS**. Аккаунты — **собственный Auth на Host** (email + пароль). Версию 1.0 не объявлять.

Tailscale и Supabase больше не обязательны в продуктивном пути (оставлены только для миграции с 0.9.3).

## С чего начать
- **[docs/0.9.4/](docs/0.9.4/)** — ТЗ, архитектура, сеть, матрица безопасности, отчёт ограничений.
- **[RELEASE_NOTES_0.9.4_RU.md](RELEASE_NOTES_0.9.4_RU.md)** — что вошло в 0.9.4.
- [Установка.md](Установка.md) — база установки (обновляется под прямой HTTPS).
- Документы 0.9.3 сохранены для истории регрессий.

## Быстрый старт Host (own Auth)

```bash
export CHELSY_AUTH_MODE=own
export CHELSY_ADMIN_EMAILS='admin1@example.com,admin2@example.com'
export CHELSY_ADMIN_PASSWORD='длинный-пароль-не-короче-15'
cd ChelsyAI_0.9_Windows
python migrations.py migrate
python host_server.py
```

Панель администратора: `python admin_panel.py` (локально).

## Состав
| Папка | Что внутри |
|---|---|
| `ChelsyAI_0.9_Windows/` | Desktop, Host API v2/v3, Windows Client, Mind, Auth, миграции, тесты |
| `Android_Client/` | Flutter Android (OwnAuth) |
| `iOS_Client/` | инструкция нативного iOS-target |
| `ChelsyGroup_Web/` | сайт и личный кабинет 0.9.4 |
| `docs/0.9.4/` | ТЗ и отчёты |

## Сборка
GitHub Actions (`.github/workflows/build-clients.yml`). Подписанные бинарники требуют секретов CI / macOS для iOS — см. отчёт 0.9.4.

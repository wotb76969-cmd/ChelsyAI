# Отчёт о реализации 0.9.4 (промежуточный)

Дата сборки исходников: 2026-11-17. Версия продукта: **0.9.4** (не 1.0).

## Сделано в исходниках

1. **Собственный Auth** (`auth/`): Argon2id, сессии, rate-limit, 2 админа, audit, user key wrap.
2. **Миграции SQLite v5–v6** (auth + mind artifacts/tasks/metrics).
3. **Host API v3** (`api_v3.py` + интеграция в `host_server.py`): login/refresh/cabinet/artifacts/admin.
4. **Chelsy Mind**: Intent, trainable Task Router (реальные веса + датасет), Planner, Policy Gateway, Artifact Builder (TXT/DOCX/PDF/PPTX/XLSX), Quality Validator.
5. **Админ-панель** (`admin_panel.py`) без просмотра частного контента.
6. **Кабинет сайта**: переработан `account.html`, `auth.js` без Supabase/jsDelivr, CSP обновлён.
7. **Документация**: матрица SEC-01, архитектура, сеть, этот отчёт, OpenAPI черновик.
8. **Тесты**: `test_auth094.py` — 11 OK; обучение router — train/val/test acc 1.0 на синтетике.

## Ограничения среды (честно, по ТЗ §8)

| Требование | Статус |
|---|---|
| Подписанные EXE/APK/IPA | Не собраны здесь (нет Windows SDK / Xcode / release keystore в этой VM). Есть воспроизводимые скрипты CI. |
| Физические iPhone / Huawei | Не испытывались в этой среде. |
| Полный LoRA 7B | Код/реестр обучения 0.9.3 сохранён; новый GPU-прогон не выполнялся — нет гарантированной VRAM. Router weights — да. |
| 150 функциональных + 50 файловых + 100 security eval | Инфраструктура генераторов и router готова; полный прогон на живой модели Ollama — у владельца Host. |
| Почтовая инфраструктура | Публичная регистрация по умолчанию выключена (`CHELSY_ALLOW_PUBLIC_REGISTER=0`). |
| Email двух админов / домен / CGNAT | Ждут данных владельца (Приложение Б). |
| Защита от root Host (TEE) | Не обещается (SEC-04). |

## Совместимость

- Клиенты 0.9.3 (Supabase/Tailscale) **не** обещаются как совместимые с новым Auth/адресом.
- Legacy `/api` и `/api/v2` оставлены на период миграции.

## Приоритет доработок владельцу

1. Задать `CHELSY_ADMIN_EMAILS` + пароль, TLS, домен.
2. Сборка подписанных артефактов в CI.
3. Прогон Ollama eval набора и опциональный LoRA на машине обучения.
4. iOS: довести Flutter target + App Store / согласованный канал.

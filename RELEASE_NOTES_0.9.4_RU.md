# Chelsy AI 0.9.4 — промежуточный релиз (исходники)

Не 1.0. Полное ТЗ: `docs/0.9.4/ТЗ_Chelsy_AI_0.9.4.txt`. Отчёт ограничений: `docs/0.9.4/REPORT_0.9.4_RU.md`.

## Главное

- **Собственный Auth** на Host (Argon2id, сессии, 2 администратора без доступа к частному контенту).
- **Прямой HTTPS** вместо обязательного Tailscale/Supabase в продуктивном пути.
- **API v3** + OpenAPI: кабинет, артефакты, админ-статус.
- **Chelsy Mind**: Intent, обучаемый Task Router (реальные веса), генераторы TXT/DOCX/PDF/PPTX/XLSX.
- **Кабинет сайта** переработан без jsDelivr/Supabase.
- **Админ-панель** Tk (локально).
- Миграции SQLite **v5–v6**.

## Клиенты

- Windows Client: вход через Host `/api/v3/auth/login`.
- Android: `OwnAuth` + Keystore; без обязательного Supabase.
- iOS: каркас и инструкция (`iOS_Client/README_0.9.4_RU.md`); IPA в этой среде не собран.

## Тесты

`cd ChelsyAI_0.9_Windows && python -m unittest discover` — 133 OK (1 skipped) + `test_auth094`.

## Не входит / честные ограничения

Подписанные EXE/APK/IPA, физические устройства, полный LoRA 7B, почтовая саморегистрация — см. отчёт.

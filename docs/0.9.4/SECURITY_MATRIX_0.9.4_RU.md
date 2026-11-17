# Матрица безопасности Chelsy AI 0.9.4 (SEC-01)

Версии ориентиров на старт работ (16.11.2026): OWASP ASVS 5.0 / MASVS 2.x / LLM Top 10 2025 / NIST AI RMF 1.0 / NIST SP 800-63B-4 / WCAG 2.2.

Формат: **контроль → реализация → проверка → доказательство → исключение**.

| Контроль | Реализация | Проверка | Доказательство | Исключение / остаточный риск |
|---|---|---|---|---|
| ASVS L2 пароли (Argon2id, длина, denylist) | `auth/passwords.py` | `test_auth094` | unit OK | MFA нет (AAL1). Для админов — расхождение с контролем MFA; компенсация: idle 15 мин, аудит, двойное подтверждение смены админов |
| ASVS сессии (короткий access, ротация refresh, reuse detection) | `auth/sessions.py` | `test_auth094` | unit OK | Cookie Secure зависит от TLS на периметре |
| ASVS CSRF / HttpOnly | cookie + SameSite=Strict в `api_v3` | ручная / браузер | код | Полный CSRF double-submit для всех форм — донастроить при same-site кабинете |
| ASVS IDOR / owner check | `mind/policy.assert_owner`, API download | `test_idor_blocked` | unit OK | — |
| MASVS storage (Keystore/Keychain/DPAPI) | Android Keystore / Windows DPAPI уже в 0.9.3; iOS Keychain — каркас | platform tests | частично | iOS бинарь не подписан в этой среде |
| LLM01 Prompt injection | содержимое = данные; Policy Gateway вне LLM | regression 0.9.3 + SEC-05 | код | Не полное покрытие всех атак |
| LLM инструменты | allowlist `ALLOWED_TOOLS` | unit policy | код | — |
| SSRF / robots | knowledge/fetcher (0.9.3) | test_network / knowledge | прежние тесты | — |
| NIST AI RMF provenance | model card / router weights hashes | `training/datasets/*` | файлы | Полный LoRA адаптер LLM — см. отчёт (нет GPU в CI) |
| 152-ФЗ / GDPR | не заявляется | — | — | Юрисдикция не задана владельцем (Приложение Б) |
| Админ ≠ чтение контента | ADM-03 API без content fields | `test_admin_list_has_no_content_fields` | unit OK | Root/Administrator Host может читать память процесса (SEC-04 граница) |

**Критические уязвимости как «исключение» не принимаются.**

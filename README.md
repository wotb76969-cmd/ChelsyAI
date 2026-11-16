# ChelsyAI

**Chelsy AI 0.9.3** — персональный ИИ-помощник Chelsy Group: нейросеть работает на вашем компьютере-хосте (Ollama), а Windows-клиент и Android-приложение подключаются к нему через частную сеть Tailscale. Единый аккаунт Chelsy Group (Supabase) на сайте, Windows и Android.

## С чего начать
- **[Установка.md](Установка.md)** — пошаговая установка хоста, Windows-клиента и Android.
- [START_HERE_RU.md](START_HERE_RU.md) — навигация по документации.
- [ChelsyAI_0.9_Windows/README_0.9.3_RU.md](ChelsyAI_0.9_Windows/README_0.9.3_RU.md) — подробная инструкция.
- [SECURITY_0.9.3_RU.md](SECURITY_0.9.3_RU.md), [TEST_REPORT_0.9.3_RU.md](TEST_REPORT_0.9.3_RU.md), [AUDIT_0.9.3_RU.md](AUDIT_0.9.3_RU.md), [RELEASE_NOTES_RU.md](RELEASE_NOTES_RU.md).

## Состав
| Папка | Что внутри |
|---|---|
| `ChelsyAI_0.9_Windows/` | Desktop (Gradio), Chelsy Host, Windows Client, движок ответов, база знаний и автоизучение, миграции, тесты, сборщики EXE |
| `Android_Client/` | Flutter-приложение для Android |
| `ChelsyGroup_Web/` | сайт Chelsy Group |
| `ChelsyAI_0.9_Windows/supabase/` | SQL-миграции Supabase и тест RLS |
| `design-system/`, `PRODUCT.md`, `CLAUDE.md` | дизайн-система и настройки плагинов дизайна |

## Сборка
GitHub Actions (`.github/workflows/build-clients.yml`) при каждом push: тесты → `ChelsyAI_Host_Setup_0.9.3.exe`, `ChelsyAI_Client_Setup_0.9.3.exe` → `ChelsyAI_Android_0.9.3.apk` (раздел Actions → Artifacts).

# Chelsy AI iOS 0.9.4

В исходной поставке 0.9.3 нативного iOS-target не было. Для 0.9.4:

## План сборки

1. Использовать тот же Flutter-проект `Android_Client` (переименовать в общий `mobile` при желании) и выполнить:
   ```bash
   cd Android_Client
   flutter create --platforms=ios .
   ```
2. Включить App Transport Security только к своему Host HTTPS.
3. Хранить refresh-токен в Keychain (`flutter_secure_storage` iOS options, `synchronizable: false`).
4. Auth: `POST /api/v3/auth/login` на адрес Host (см. `lib/src/own_auth.dart`).
5. Подпись и канал распространения — на macOS с Xcode; TestFlight/AltStore не должны быть обязательным пользовательским путём (NET-04).

## Ограничение этой среды

macOS/Xcode здесь отсутствует — подписанный IPA не собран. Каркас Auth и документация подготовлены; воспроизводимая сборка — на машине с Apple toolchain.

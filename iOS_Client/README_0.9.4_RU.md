# Chelsy AI для iOS 17+

Проект Xcode находится в Android_Client/ios/Runner.xcworkspace. Оба мобильных клиента используют один исходный код Flutter 3.50.0. Bundle ID по умолчанию задаёт проект Runner. Согласуйте его со своим идентификатором в Apple Developer до подписи.

На macOS установите Xcode с iOS SDK, принятыми условиями лицензии и Flutter 3.50.0. Проверьте инструменты через `flutter doctor -v`. В каталоге Android_Client выполните `flutter pub get`, `flutter analyze`, `flutter test`, затем `flutter build ios --simulator --debug --no-codesign`. Откройте Runner.xcworkspace, выберите Runner → Signing & Capabilities → свою Team. Проверьте Keychain Sharing, Deployment Target 17.0 и сертификат распространения. Для App Store Connect используйте Product → Archive → Distribute App или `flutter build ipa --release` с настроенными идентификатором, сертификатом и профилем. Только владелец Apple Developer определяет канал публикации.

В приложении задайте HTTPS-адрес Host и войдите своим email и паролем. Кнопка документов в верхней панели открывает Chelsy Mind. Откройте диалог сохранения готового файла и выберите «Сохранить в Файлы». Для проверки на устройстве повторите скачивание из мобильной сети, отзыв сессии и повторный вход после перезапуска. Фактический статус сборки и проверки на устройстве приведён в ACCEPTANCE_0.9.4_RU.md.

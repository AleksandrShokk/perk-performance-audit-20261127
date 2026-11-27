# PERK · мобильное приложение

Expo SDK 58, React Native 0.88, React 19 и TypeScript. Основные разделы первой версии:
обзор, товары, финансы, остатки, поставки, магазины, профиль и сотрудники.
Разрабатываем мобильный клиент; сайт и расширение — следующие этапы.
Ozon: подключение ключа готово, чтение данных — следующий этап. [Подключение Ozon](docs/OZON.md).

## Документация

- [Архитектура и карта папок](docs/ARCHITECTURE.md).
- [Аудит первой версии, проверки и оставшаяся работа](docs/MOBILE-V1-AUDIT.md).
- [История проверки на телефонах](docs/REVIEW-FIXES.md).
- [План развития обзора](docs/HOME-PLAN.md).

## Запуск

Нужны Node.js 24, pnpm 12 и Expo Go для SDK 58.

```powershell
pnpm install --frozen-lockfile
Copy-Item apps/mobile/.env.example apps/mobile/.env
pnpm --filter mobile start
```

В `.env` задайте `EXPO_PUBLIC_API_URL`: адрес локального API, доступный с телефона.
`localhost` на телефоне означает сам телефон. Адрес может включать `/api/v1`.
Для проверки в браузере можно отдельно задать `EXPO_PUBLIC_WEB_API_URL`:
см. `.env.example` и `src/lib/config.web.ts`. На web используются cookies/CSRF,
на устройствах — Bearer и SecureStore. Ключи WB и пароли в `EXPO_PUBLIC_*` не помещаются.

Сервер находится в соседнем `../BACK`; текущая миграция — `0023_mobile_supplies`.
Приложение не применяет миграции автоматически. В локальной разработке Telegram
оставлен в режиме fake, письма доступны через Mailpit. Настройка — в документации бека.

## Команды

```powershell
pnpm check                  # lint + TypeScript + тесты
pnpm lint                   # весь фронт, без generated
pnpm ts-check               # TypeScript мобильного клиента и общих пакетов
pnpm test                   # проверки логики, сессии, HTTP и кэша
pnpm api:generate           # OpenAPI бека → запросы, типы и Zod
pnpm --filter mobile exec expo install --check
```

Нативные зависимости добавляются через `pnpm --filter mobile exec expo install`.
Локальные workspace-пакеты подключаются через pnpm, например
`pnpm --filter mobile add @app/api@workspace:*`.

При перемещении файлов Metro обычно обновляет импорты сам. Если редактор или запущенный
сервер сохранил старый путь, перезапустите свой процесс Expo с `--clear`.
Не запускайте второй сервер на занятом порту 8081.

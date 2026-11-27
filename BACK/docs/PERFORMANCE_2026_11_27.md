# Скорость сайта: правки от 27.11.2026

## Что изменено

| Что | Где | Зачем |
|---|---|---|
| Замер времени каждого запроса API | `app/core/timing.py`, `app/main.py`, `app/db/session.py`, `app/security/crypto.py` | Видно, сколько времени уходит на SQL, на расшифровку и на остальное |
| 3 процесса API вместо одного | `deploy/compose.production.yaml` (`WEB_CONCURRENCY`) | Дашборд шлёт ~8 запросов параллельно, а один процесс Python считает их по очереди на одном ядре |
| Кэш финансового отчёта и графиков живёт 12 ч вместо 15 мин | `app/modules/finance/report.py`, `app/modules/sync/analytics.py` | Ключ кэша содержит ревизию данных, поэтому старые цифры показаны не будут. Раньше после 15 минут без заходов любое открытие сайта пересчитывало отчёт с нуля |
| Попадание в кэш больше не перешифровывает и не перезаписывает отчёт | там же | Минус одно шифрование и одна запись в Redis на каждое открытие |
| Ключ AES-GCM готовится один раз, а не на каждую строку | `app/security/crypto.py` | Мелочь: 1.5 → 0.6 мкс на строку. Замер показал, что само шифрование быстрое и вряд ли даёт секунды |
| `pg_stat_statements` и `track_io_timing` | `deploy/compose.production.yaml` (postgres) | Точный топ медленных SQL-запросов |

Что сознательно **не** менялось:

- **Частота Celery Beat.** После каждой страницы загрузки WB задача ждёт следующего тика
  `perk.sync.dispatch` (каждые 2 с). Если сделать 10 с, первичная загрузка года станет
  медленнее. Нагрузка от опроса на сервере ничтожная: load average 0.2.
- **Настройки PostgreSQL** (`random_page_cost` и подобные). База 393 МБ целиком в памяти,
  кэш попадает в 98% случаев — эффекта не будет.

## Как выкатить

На сервере, после того как новые файлы `BACK/` и `deploy/` лежат в `/opt/perk`:

```bash
cd /opt/perk/deploy
```

```bash
./compose.sh build api
```

Пересоздать postgres: у него новые параметры запуска. База перезапустится на несколько
секунд, лучше делать вечером.

```bash
./compose.sh up -d --wait --force-recreate postgres
```

Пересоздать **все** контейнеры бэкенда, а не только API. Сейчас `worker`, `worker-ozon`
и `beat` работают на образе от 15 ноября, старее API.

```bash
./compose.sh up -d --wait --force-recreate api worker worker-ozon worker-heavy beat
```

Один раз включить расширение, от админ-пользователя PostgreSQL:

```bash
./compose.sh exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"'
```

Откат: вернуть прошлую версию `compose.production.yaml` и образ. Миграций базы нет.

Количество процессов API задаётся переменной `API_WORKERS` (по умолчанию 3). Если памяти
мало, поставьте 2.

## Как смотреть замеры

### В браузере (самый простой способ)

1. Откройте сайт, нажмите F12 и перейдите на вкладку **Network** (Сеть).
2. Обновите страницу. В фильтре выберите **Fetch/XHR**.
3. Кликните любой запрос `/api/v1/...` и откройте вкладку **Timing**. Внизу будет блок
   **Server Timing**:
   - `db` — время в PostgreSQL и число SQL-запросов;
   - `crypto` — расшифровка и шифрование;
   - `app` — всё остальное в Python: расчёты, сборка JSON;
   - `total` — весь запрос на сервере.

Если `total` маленький, а запрос в браузере долгий — дело в сети или во фронтенде.
Если большой — видно, какая часть тормозит.

### В логах сервера

Каждый запрос дольше 1 секунды пишется одной строкой, без идентификаторов и данных:

```
slow_request method=GET route=/api/v1/workspaces/{workspace_id}/finance/overview status=200 total_ms=4210 db_ms=950 sql=63 crypto_ms=2400 crypto_ops=1800
```

Собрать за день:

```bash
./compose.sh logs --since 24h api | grep slow_request
```

Порог меняется переменной `SLOW_REQUEST_MS`.

### Топ медленных SQL

После включения `pg_stat_statements` и часа обычной работы:

```sql
SELECT calls, round(total_exec_time) AS total_ms, round(mean_exec_time, 1) AS mean_ms,
       left(query, 120) AS query
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20;
```

Эти три источника и покажут, что делать дальше: кэш агрегата `/business`, перенос
расшифровки или переделку записи метрик при загрузке.

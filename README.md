# trade-signal-collector

**EN · What it is:** CLI collector of international trade signals for B2B
outreach, built on the official **UN Comtrade API** (imports/exports by
country, partner, HS code, period) with a pluggable company-level layer
(customs manifests import, freight-forwarder noise filtering).

**Works out of the box** via the free public preview channel
(`public/v1/preview`, no key required; limits: 1 period per request,
~1 request/minute). **To scale** (multi-period, higher rate limits, full
`data/v1/get` coverage) register a free UN Comtrade API key at
comtradeplus.un.org and put it in `.env` as `COMTRADE_API_KEY=` — see
`.env.example`. No key = no problem for pilots; the key just removes limits.

Импортно-экспортные сигналы для международного B2B-аутрича. Реализация
по ТЗ (см. историю); стек: Python 3.12+, только стандартная библиотека;
SQLite; без внешних сервисов по умолчанию.

## Статусы источников (2026-09-18)

| Источник | Статус | Причина |
|---|---|---|
| comtrade-preview | **LIVE_VERIFIED** | public/v1/preview без ключа; 1 период/запрос, ~1 запрос/мин; живой прогон 6/6 success |
| comtrade data/v1 | KEY_REQUIRED | ключ после регистрации comtrade - v1 (полный канал: мульти-период, aggregateBy) |
| importyeti | **BLOCKED** (technical) | robots: Allow /, но /search?q и /api/* запрещены; главная и профиль → HTTP 403 Cloudflare (2026-09-17); обход не закладываем |
| csvimport | **LIVE_VERIFIED** | локальный CSV-импорт без сети |

Живые данные (HS 8422, импорт из мира): DEU $2.07B (+0.5% YoY),
GBR $1.38B (+2.6%), USA $6.07B (+3.3%) — 2024 против 2023.

## Команды

```powershell
$uv = "$HOME\.local\bin\uv.exe"; $env:PYTHONPATH = "$PWD\src"
& $uv run --python 3.12 python -X utf8 -m tradesignal doctor --config config/queries.example.json
& $uv run --python 3.12 python -X utf8 -m tradesignal collect --config config/queries.example.json --dry-run
& $uv run --python 3.12 python -X utf8 -m tradesignal collect --config config/queries.example.json   # требует .env ключ
& $uv run --python 3.12 python -X utf8 -m tradesignal import --kind stat --file examples/demo_stat_import.csv
& $uv run --python 3.12 python -X utf8 -m tradesignal import --kind companies --file examples/demo_companies_import.csv
& $uv run --python 3.12 python -X utf8 -m tradesignal import --kind shipments --file examples/demo_shipments_import.csv
& $uv run --python 3.12 python -X utf8 -m tradesignal signals --partner CHN
& $uv run --python 3.12 python -X utf8 -m tradesignal status
& $uv run --python 3.12 python -X utf8 -m tradesignal export --kind signals --out data/export/signals.csv
```

## Ключи (владелец регистрирует на свой e-mail)

Скопировать `.env.example` → `.env` и заполнить:
- **COMTRADE_API_KEY** — https://comtradeplus.un.org/ → Sign Up → профиль → API Key.
  Бесплатная подписка; фактические лимиты зафиксировать в reports/access-feasibility.md.
- **CENSUS_API_KEY** (пилот) — https://api.census.gov/data/key_signup.html,
  активация по ссылке из письма.

После ключа: `collect` → live-приёмка по ТЗ (одна страна, один HS6,
12 месяцев, ручная сверка 3 значений с UI портала).

## Структура

```
src/tradesignal/
  models.py        # TradeQuery/StatRow/CompanyRecord/forwarder_suspect
  config.py        # JSON-конфиг + .env
  transports/http.py  # urllib, SSRF-защита, бюджет, ретраи, Retry-After
  rawstore.py      # gzip JSON, redaction секретов
  storage.py       # stat_observations(+history), companies, shipments, signals, runs
  signals.py       # yoy_growth / partner_share / growth_streak
  scheduler.py     # прогоны, raw-first, честные статусы
  export.py        # CSV UTF-8 BOM + formula-guard, JSONL
  sources/         # comtrade / importyeti (BLOCKED) / csvimport
tests/             # 26 тестов, fixtures, без сети
```

## Правила честности (суть)

- лаг публикации статистики ~2–3 мес: `period` данных ≠ дата наблюдения;
- HS2/HS4/HS6 не смешиваются (`hs_length`);
- consignee ≠ покупатель: freight-forwarder шум помечается `ff_suspect`;
- вес/количество в манифестах заявленные;
- исчезновение ряда из выдачи не удаляет его и не означает «торговля прекратилась»;
- сигнал статистики — факт; использование в аутриче — отдельное поле `hypothesis`.

# progress.md — trade-signal-collector

Цель: сборщик импортно-экспортных данных для международного аутрича
по ТЗ `../trade_data_parser_spec.md`.

## Состояние (2026-09-18): приёмка ЗАВЕРШЕНА ✅

- **comtrade data/v1 (с ключом): LIVE_VERIFIED.** Мульти-периодные запросы,
  3 запроса → 6 рядов, повторный прогон идемпотентен (unchanged=6).
- **Перекрёстная сверка каналов: 6/6 совпало, 0 расхождений** —
  data/v1/get и public preview дают идентичные значения (DEU/GBR/USA ×
  2023/2024). Независимая валидация парсинга total-строк
  (`scripts/compare_channels.py`).
- **comtrade-preview: LIVE_VERIFIED** (без ключа; 1 период/запрос,
  ~1 запрос/мин).
- Тесты: **29/29 OK**. Репозиторий: github.com/uobt/trade-signal-collector.

Реальные ряды (HS 8422, импорт из мира): DEU $2.07B (+0.5% YoY),
GBR $1.38B (+2.6%), USA $6.07B (+3.3%) — 2024 против 2023.

## Как получали ключ (для истории)

comtradeplus.un.org теперь кидает на developer-портал Azure APIM:
comtradedeveloper.un.org → Sign in → Products → Free APIs → Subscribe →
письмо-подтверждение → Profile → Primary key → .env (32 символа).

## Осталось (не блокирует)

1. Партнёрские ряды (partner=156 CHN и др.) для partner_share —
   +1 запрос на страну/период/партнёра.
2. Расширение ISO3↔numeric словаря по мере добавления стран.
3. ImportYeti: письмо в partnerships (легальный путь к контуру B).

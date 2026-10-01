# Реальный сбор после открытия сетевого доступа

**Завершено 28 сентября 2026:** 19 из 19 основных ACS-таблиц, CDC PLACES tract для трёх health measures и две отдельные ACS alternatives. Основной запуск начат в 18:38 UTC и завершён в 18:49 UTC; alternatives завершены в 18:50 UTC. Все supervisors имеют `complete`, exit code 0; фоновые workers завершились.

Этот результат отделён от [исторического offline recovery](README.md). Здесь учтены реально скачанные официальные payloads. Новый набор находится в `full/runtime/deep-20260928/`, который исключён из Git локальным `.gitignore`. Production admission и изменения UI этим агентом не выполнялись.

## Итоговые объёмы

| Набор | Нормализованных записей | Raw gzip, байт | Normalized gzip, байт |
|---|---:|---:|---:|
| Основной ACS: 19 таблиц | 71 263 721 | 388 976 787 | 440 386 329 |
| CDC: 83 522 tracts × 3 measures | 250 566 | 2 188 753 | 4 278 619 |
| **Основной сбор всего** | **71 514 287** | **391 165 540** | **444 664 948** |
| Extension B17021: poverty counts | 726 568 | 52 301 501 | 6 985 460 |
| Extension B05012: nativity counts | 358 905 | 4 856 833 | 3 623 768 |
| **Extensions отдельно** | **1 085 473** | **57 158 334** | **10 609 228** |
| **Все наборы** | **72 599 760** | **448 323 874** | **455 274 176** |

Всего raw + normalized: **903 598 050 байт**, без небольших metadata/log/checkpoint. Одна ACS-запись — пара estimate/MOE одной исходной переменной и географии; это не число самостоятельных пользовательских показателей. Extensions намеренно сохраняют альтернативную source lineage и содержат пересекающиеся с основным набором измерения.

Последний снимок [live-coverage.json](live-coverage.json) и [live-coverage.csv](live-coverage.csv) содержит все **81 catalog fields**: 23 ACS-поля имеют все требуемые исходные таблицы, три CDC-поля собраны как отдельная crude variant, семь food-полей исключены, 48 полей относятся к другим источникам и не входят в этот ACS/CDC run. Snapshot повторно проверил SHA-256 всех **44 raw/normalized файлов**. Completion source tables не означает, что все доли/ratios уже вычислены либо допущены в БД.

## Фактическая глубина

Обычное покрытие ACS: **242 297 block groups, 85 382 tracts, 3 222 counties, 32 330 places, 52 states/DC/PR и одна nation-строка**. У B19301 фактически 242 069 BG, 85 326 tracts и 31 741 place. Отсутствующие географии не заполняются соседними или более крупными значениями.

**Бедность теперь собрана на 242 297 BG через B17021.** Сохранены `B17021_001` — population for whom poverty status is determined, и `B17021_002` — число людей ниже порога бедности. Доля требует деления numerator/denominator и корректного MOE. Для этих двух counts 177 208 общих county/tract пар полностью совпадают с B17001 по estimate, MOE и quality; несовпадений и unmatched candidate pairs — 0.

**B05012 не даёт block groups:** получены 84 401 tracts, 3 144 counties, 32 038 places, 51 state/DC и одна nation-строка. Для total и foreign-born count 175 090 общих county/tract пар полностью совпадают с B05002; несовпадений и unmatched candidate pairs — 0. B05012 содержит total/native/foreign-born и не заменяет полный 27-variable breakdown B05002. Universe — total population in the United States, без Puerto Rico.

Пределы подтверждены одновременно payloads и скачанным [официальным 2024 Data Product List](https://www2.census.gov/programs-surveys/acs/tech_docs/table_shells/table_lists/2024_DataProductList.xlsx). B05001, B05002, B05005, B05006, B05012 и B17001 исключают BG; B17021 их допускает. Исходный XLSX, его hash и извлечённые universe/restrictions лежат в `metadata/`. Для 21 таблицы также сохранены official group JSON и словарь 1 948 variables. Никакой downscale или подмены county/tract значениями BG нет.

CDC: **83 522 tracts × obesity, diabetes, physical inactivity = 250 566 observations**, variant `crude_prevalence`, data year **2023**, tract vintage **2023**, 95% CI. Это отдельная серия относительно текущего county age-adjusted контракта. До/после загрузки проверены metadata release `2025`, dataset revision и точное число строк.

Официальные источники данных: [ACS 2024 5-year Summary File](https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/), [CDC PLACES 2025 tract](https://data.cdc.gov/500-Cities-Places/PLACES-Census-Tract-Data-GIS-Friendly-Format-2025-/yjkw-uj5s).

## Завершённые таблицы

Counts — реальные уникальные географии данного файла. Размеры относятся к сжатым артефактам. `0 BG` означает отсутствие этого уровня в официальном payload.

| Job | BG | Tract | County | Записей E/M или CDC | Raw, байт | Normalized, байт |
|---|---:|---:|---:|---:|---:|---:|
| acs-summary-B01001 | 242 297 | 85 382 | 3 222 | 17 800 916 | 79 437 348 | 122 210 480 |
| acs-summary-B01002 | 242 297 | 85 382 | 3 222 | 363 284 | 8 666 068 | 3 521 862 |
| acs-summary-B01003 | 242 297 | 85 382 | 3 222 | 363 284 | 5 443 706 | 3 905 118 |
| acs-summary-B03002 | 242 297 | 85 382 | 3 222 | 7 628 964 | 28 973 495 | 50 337 309 |
| acs-summary-B05001 | 0 | 84 401 | 3 144 | 717 810 | 7 033 618 | 6 092 969 |
| acs-summary-B05002 | 0 | 85 382 | 3 222 | 3 266 649 | 21 536 788 | 23 154 131 |
| acs-summary-B05005 | 0 | 84 401 | 3 144 | 2 512 335 | 14 476 551 | 16 463 935 |
| acs-summary-B05006 | 0 | 84 401 | 3 144 | 21 295 030 | 37 911 708 | 86 265 001 |
| acs-summary-B08301 | 242 297 | 85 382 | 3 222 | 726 568 | 25 625 639 | 7 245 606 |
| acs-summary-B15003 | 242 297 | 85 382 | 3 222 | 9 082 100 | 30 855 887 | 57 381 941 |
| acs-summary-B17001 | 0 | 85 382 | 3 222 | 241 974 | 47 603 959 | 2 375 382 |
| acs-summary-B19001 | 242 297 | 85 382 | 3 222 | 726 568 | 26 770 605 | 6 932 938 |
| acs-summary-B19013 | 242 297 | 85 382 | 3 222 | 363 284 | 5 536 601 | 4 581 894 |
| acs-summary-B19301 | 242 069 | 85 326 | 3 222 | 362 411 | 5 473 358 | 4 566 353 |
| acs-summary-B25003 | 242 297 | 85 382 | 3 222 | 726 568 | 9 605 464 | 6 955 560 |
| acs-summary-B25064 | 242 297 | 85 382 | 3 222 | 363 284 | 4 179 255 | 3 476 035 |
| acs-summary-B25070 | 242 297 | 85 382 | 3 222 | 3 996 124 | 15 713 827 | 26 746 732 |
| acs-summary-B25077 | 242 297 | 85 382 | 3 222 | 363 284 | 5 541 256 | 4 427 445 |
| acs-summary-B25088 | 242 297 | 85 382 | 3 222 | 363 284 | 8 591 654 | 3 745 638 |
| cdc-places-2025-tract | 0 | 83 522 | 0 | 250 566 | 2 188 753 | 4 278 619 |
| extension: acs-summary-B05012 | 0 | 84 401 | 3 144 | 358 905 | 4 856 833 | 3 623 768 |
| extension: acs-summary-B17021 | 242 297 | 85 382 | 3 222 | 726 568 | 52 301 501 | 6 985 460 |

## Проверка и продолжение

Из корня data-репозитория:

```bash
python3 ops/start_deep_collection.py status
python3 ops/collect_deep_extensions.py status

# Проверить hashes всех завершённых файлов и обновить обе live matrices.
python3 research/2026-09-28/geography/snapshot_live.py

# Логи завершённого сбора.
tail -n 20 full/runtime/deep-20260928/acs-summary.log
tail -n 20 full/runtime/deep-20260928/cdc-places.log
tail -n 20 full/runtime/deep-20260928/extensions/extensions.log

# Идемпотентное продолжение после остановки, если потребуется.
python3 ops/start_deep_collection.py start
python3 ops/collect_deep_extensions.py start

# Воспроизводимое получение official metadata.
python3 ops/fetch_deep_metadata.py
```

Provider manifests: `run-acs-summary.json`, `run-cdc-places.json`, `extensions/run-acs-summary.json`. В них сохранены source URL, retrieval timestamp, release/data period/geography vintage, quality counts, SHA-256 raw/normalized, размеры и native coverage. Сравнения альтернатив: `extensions/metric-equivalence.json`; metric identity/denominators: `extensions/extension-metrics.json`. Collector SHA-256 зафиксирован: `c19a470270c64d419eb7b9780647c0a85daccc1b493478b530afbf7eefde8500`.

Workers запускались через `start_new_session=True`, stdin `/dev/null`, stdout/stderr в постоянные журналы. По одному `flock` на провайдера, manifests не пересекаются. Supervisor повторяет только transient network/HTTP 408, 429, 500, 502, 503, 504 с задержкой 15–600 секунд, максимум 24 попытки. Все три supervisors завершились с первой попытки. Завершённый table checkpoint переиспользуется после проверки hashes; прерванный table download повторяется целиком. Code/contract/plan/geographies привязаны хешами: при намеренной смене кода или плана нужен новый `--out`.

Payload limit — 4 GiB, минимальный запас диска — 2 GiB. Полные jobs принимают HTTP 200; HTTP 206 разрешался только для явно отдельного ограниченного format probe. Нормализация сохраняет estimate/MOE, специальные source tokens и различает missing, suppressed и not-collected. EA/MA annotation columns в Summary File отсутствуют, это обозначено в манифестах. Выбираются только стандартные полные GEO_ID, тематические модификаторы не смешиваются с основными географиями.

Перед полным запуском прошли **13 regression tests**: E/M parsing, raw-sentinel/missing, typed GEOIDs, national variants, дубликаты/неправильная ширина CSV, запрет downscale, географические counts, damaged cache. Финальный snapshot дополнительно проверил hashes всех 44 файлов и записал JSON/CSV с 81 полем.

## Что ещё нужно для использования

- Admission adapter с quality/uncertainty и ссылками catalog→source-series; рекомендации в [ADMISSION-NOTES.md](ADMISSION-NOTES.md).
- Вычисление долей с корректными denominator/universe/MOE, географическое пересечение разных таблиц для составных метрик.
- Геометрии нужного vintage, поддержка tract/BG и ограниченных пространственных запросов в UI.
- Другие 48 catalog fields требуют своих провайдеров/отдельных запусков; этот run не заявляет полноту всех 81 тем.

Food `08.01`, `08.02`, `08.03`, `08.06`, `09.01`, `09.02`, `09.03` исключены. Коммит/пуш и production admission этим агентом не выполнялись.

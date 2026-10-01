# Географическая глубина: результат на 28 сентября 2026

**Обновление после открытия сети:** реальный ACS/CDC сбор завершён: 19 основных ACS-таблиц, CDC tract и две ACS alternatives; всего 72 599 760 исходных записей. Бедность дополнительно собрана на 242 297 block groups через B17021. Актуальный запуск описан в [LIVE-COLLECTION.md](LIVE-COLLECTION.md), результаты — в [live-coverage.json](live-coverage.json). Ниже сохранён исторический отчёт предыдущего offline этапа.

**Выполнено восстановление имеющегося проверенного Census-кэша, а не свежая загрузка полного набора.** Получены 1 759 850 уникальных записей «география × переменная», каждая с местом для estimate и MOE. Возраст и пол (`01.02`, `01.03`) восстановлены **частично**. Новых block group: **0**. Новых скачанных через сеть наблюдений: **0** — обычные HTTPS-запросы из среды остановлены ошибкой DNS `network_gaierror`. Страницы источников доступны через инструмент веб-исследования; их чтение не считается скачиванием данных.

`country` в задаче интерпретирован как **county**. Из нового сбора исключены еда/напитки/рестораны/магазины/food access: `08.01`, `08.02`, `08.03`, `08.06`, `09.01`, `09.02`, `09.03`. Fitness (`09.04`), obesity и diabetes остаются в области задачи.

Дополнительно выполнены два ограниченных запроса данных через web-инструмент: CDC JSON на 3 tracts и Census population E/M для BG одного tract. Оба вернули `URL is not accessible via this tool`, строк не получено. Это ограничение инструмента, а не доказательство HTTP-отказа провайдера. URL и результаты сохранены в [web-data-probes.json](web-data-probes.json); повторные обходные попытки не выполнялись.

## Что реально лежит на диске

| Нативная география | Географий | Записей estimate/MOE | Покрытие |
|---|---:|---:|---|
| State | 52 | 1 300 | 50 штатов, DC, Puerto Rico |
| County | 3 222 | 80 550 | 52 state-кода исходного кэша |
| Place | 32 330 | 808 250 | 52 state-кода исходного кэша |
| Tract | 34 790 | 869 750 | 20 state-кодов, перечислены в манифесте |
| Block group | 0 | 0 | Не было в исходном кэше |
| **Всего** | **70 394** | **1 759 850** | **Неполные темы и неполное tract-покрытие** |

Проверены SHA-256, исходные binding-sidecars и соответствие старым `collect.py`, contract и adapter config у всех **132 gzip-файлов**: 125 data payloads и 7 metadata payloads. Из старого checkpoint нельзя вывести текущее покрытие: он был снят раньше и описывает только 36 Census jobs. Фактический набор файлов проверен заново.

В этих запросах был только `pack-00`: `B01001_001E/M`…`B01001_024E/M` и `B01001_025E`. Получено:

- 1 759 850 числовых оценок;
- 1 685 485 числовых MOE;
- 3 971 MOE со специальным кодом `-555555555` — controlled estimate;
- 70 394 отсутствующих MOE `B01001_025M`, которые не попали в первый пакет;
- EA/MA annotation columns не запрашивались старым сборщиком, это явно отмечено `not_collected`.

Возрастные категории и распределение по полу не завершены: отсутствуют остальные B01001-переменные, а для Age ещё и медианный возраст B01002. Общая численность есть внутри B01001, но она **не подменяет автоматически** контрактный population `01.01`, который использует B01003. Дублирование одного B01001-наблюдения для полей Age и Sex устранено через отдельный словарь соответствий [recovered-series.json](recovered-series.json).

Локальные артефакты:

- [data/recovered-acs-2024.csv.gz](data/recovered-acs-2024.csv.gz) — **10 351 829 байт**, SHA-256 `97e7164c98f7ee76a9d2e5d9531e8b98d8d4d56094d23ba48e11fca2584d734e`;
- [data/recovered-geographies-2024.csv.gz](data/recovered-geographies-2024.csv.gz) — **531 976 байт**, SHA-256 `16bba66f520fb29fb42f403205a46cabb95cdfd2798b303204cbd8b2539cface`;
- [cache-recovery-manifest.json](cache-recovery-manifest.json) — все исходные хеши, counts, state coverage, пропуски, выпуск и ограничения;
- [coverage-matrix.json](coverage-matrix.json) и [coverage-matrix.csv](coverage-matrix.csv) — **все 81 поле**, exclusions, старое объявленное покрытие, локальные доказательства, допустимая глубина/неразрешённые ограничения, источник, probe и следующий шаг.

`data/` и `raw/` игнорируются локальным `.gitignore`. Они воспроизводятся из versioned-кэша и не увеличивают Git-историю. Манифесты, код, словарь и coverage matrix подлежат версионированию. Коммит/пуш не выполнялся. В production БД ничего не записывалось; наличие строк в живой БД не проверялось. Исторический `pass` в манифесте не означает, что исключённый из Git большой артефакт присутствует в этом checkout. FBI/EIA integration fixtures проверены по хешам и отдельно отмечены в матрице.

## Куда реально можно углубиться

| Семейство | Действие и предел |
|---|---|
| ACS, 23 поля / 19 таблиц | Собрать county/tract/BG из table-based Summary File; сохранять только реально опубликованные GEO_ID. Для обычных демографических, жилищных и доходных таблиц целевой уровень — BG. Для четырёх B050xx-тем (nativity, birthplace, citizenship, entry) консервативно оставлена tract-кандидатура до проверки ограничений конкретных таблиц. |
| CDC PLACES, 3 поля | Официальный tract dataset есть. **В выбранном tract GIS-файле crude prevalence**, тогда как текущий county контракт использует age-adjusted prevalence. Новый сбор имеет отдельный variant; 95% CI и model-based статус обязательны. |
| BLS LAUS | County — национальный слой; существуют также официальные серии отдельных cities/city parts. Tract/BG этой серии не подтверждены. |
| FBI | Agency/ORI с месяцами участия и coverage. ORI не является county/place-полигоном. |
| CDC mortality, 12 полей | County; подавление малых значений сохранять. Публичный WONDER API запрещает geographic group/filter для NVSS: нужен разрешённый экспорт или опубликованный файл. |
| Life expectancy | Найден USALEEP tract baseline **2010–2015**, а не актуальная ежегодная серия. Не смешивать с границами 2024 без crosswalk. |
| HUD homelessness | Нативная CoC, границы которой не обязаны совпадать с county. |
| IRS | Нативные ZIP и отдельные county-файлы; ZIP не ZCTA. |
| BEA / EIA / EPA | Metro / utility×state×sector / monitor соответственно; принудительного BG-слоя нет. |
| Остальные неопределённые поля | В матрице сохранены definition/source/license blockers; найденные альтернативы не объявлены готовыми или тождественными текущим показателям. |

ACS API теперь [требует API key для data queries](https://api.census.gov/data/2024/acs/acs5/examples.html). Поэтому новый сборщик использует [официальный table-based Summary File](https://www.census.gov/programs-surveys/acs/data/summary-file.2024.html): отдельные `.dat` содержат estimates и MOE, доступны без прикладного API-ключа. Выбираются только 19 нужных таблиц, а не общий архив 12 GB. [Официальный каталог файлов](https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/) подтверждает их существование; сами payloads здесь не скачаны.

[ACS Detailed Tables](https://www.census.gov/data/developers/data-sets/acs-5year.html) в целом поддерживают block group, но [release rules](https://www2.census.gov/programs-surveys/acs/tech_docs/data_suppression/ACS_Data_Release_Rules.pdf) предусматривают ограничения некоторых тем. [2024 Table List](https://www2.census.gov/programs-surveys/acs/tech_docs/table_shells/table_lists/2024_DataProductList.xlsx) найден, но XLSX не прочитан доступным web-инструментом. Поэтому точный предел B050xx **не выдан за проверенный факт**. Сборщик определяет тип по фактическому `GEO_ID`, не создаёт отсутствующих BG и не делит county/tract-значения между меньшими территориями.

[PLACES tract 2025](https://data.cdc.gov/500-Cities-Places/PLACES-Census-Tract-Data-GIS-Friendly-Format-2025-/yjkw-uj5s) содержит 83 522 строки; для трёх выбранных показателей указан 2023 data year и tract boundaries 2023. Идентификатор ресурса может переиспользоваться CDC. Сборщик сверяет название выпуска и `rowsUpdatedAt` до/после скачивания, точное число географий и явно останавливается при изменении выпуска/покрытия. Показатели еды в запрос не включены.

Остальные подтверждения: [географии LAUS](https://www.bls.gov/lau/laugeo.htm), [FBI UCR](https://www.fbi.gov/how-we-can-help-you/more-fbi-services-and-information/ucr), [ограничения WONDER API](https://wonder.cdc.gov/wonder/help/wonder-api.html), [USALEEP](https://www.cdc.gov/nchs/nvss/usaleep/update/usaleep.html), [HUD AHAR](https://www.huduser.gov/portal/datasets/ahar.html), [IRS county](https://www.irs.gov/statistics/soi-tax-stats-county-data-2022), [BEA RPP](https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area), [EIA 861](https://www.eia.gov/electricity/data/eia861/), [EPA AirData](https://aqs.epa.gov/aqsweb/airdata/download_files.html). В матрице ссылки привязаны к полям.

## Запуск и продолжение

Все команды выполнять **из корня data-репозитория**, Python 3.11+, только stdlib:

```bash
python3 full/collect_deep.py recover-cache
python3 research/2026-09-28/geography/build_inventory.py
python3 full/collect_deep.py plan
python3 -m unittest discover -s research/2026-09-28/geography -p 'test_collect_deep.py' -v
```

На машине с доступом к официальным HTTPS-источникам:

```bash
# Один ограниченный national-table job; ключи не используются.
python3 full/collect_deep.py collect --provider acs-summary --max-jobs 1

# Все 19 ACS-таблиц, нативные county/tract/BG.
python3 full/collect_deep.py collect --provider acs-summary --max-jobs 19

# CDC: только obesity, diabetes, physical inactivity; tract, crude, CI.
python3 full/collect_deep.py collect --provider cdc-places --max-jobs 1
```

Повтор той же команды пропускает завершённые jobs **только после проверки SHA-256** raw/normalized; повреждённые файлы не принимаются. Незавершённая загрузка повторяется на уровне отдельной таблицы, byte-range resume отсутствует. На каждый payload установлен лимит 1 GiB, проверяется свободное место, запросы идут последовательно. По умолчанию выполняется один job. При блокировке exit code **2**, статус `partial_or_blocked`; это не `pass`. [run-acs-summary.json](run-acs-summary.json) и [run-cdc-places.json](run-cdc-places.json) содержат фактические неудачные попытки 28 сентября.

Изменение кода/контракта/плана/наборов geography блокирует старый checkpoint. Для намеренно нового выпуска/версии используйте `--out research/2026-09-28/geography/new-run-name`; прежнее состояние не переписывать. Возврат `complete` означает завершение выбранных jobs этого сборщика, **не полноту всех 81 тем и не admission в БД**. Успешный будущий онлайн-сбор нужно отразить новым аудитом coverage: текущий `build_inventory.py` составляет датированный offline-аудит и не объявляет будущие online artifacts готовыми автоматически.

## Формат и проверка

Одна CSV-строка — одна нативная пара `(geo_type, geo_id, variable)`; выпуск/период/источник лежат в манифесте, каталог и labels — в `recovered-series.json`, названия географий — в отдельном gzip CSV. GEOID хранится строкой: county 5, tract 11, BG 12 знаков; leading zeros сохраняются. Геометрии в этом этапе не скачивались. Для старого кэша географический выпуск помечен как **2024 ACS publication geography**, а не неподтверждённый файл границ. Подход отделяет компактные наблюдения от повторяющихся URL/названий.

Числовые estimate/MOE находятся в своих колонках. `missing` (провайдер вернул пустое) и `not_collected` (колонки не было) различаются. Специальные raw-коды сохранены в `estimate_code/moe_code`, а числовые значения для них пусты. [Описание Census sentinel codes](https://www.census.gov/data/developers/data-sets/acs-1year/notes-on-acs-estimate-and-annotation-values.html) использовано для статусов. `-555555555` не становится отрицательной ошибкой или безусловным нулём. В summary-файлах EA/MA может не быть: формат сохраняет source tokens и явно указывает отсутствие annotation columns; такие ряды нельзя считать готовыми для интерпретации открытых median intervals без дополнительной проверки.

Проверено: **11 unit tests** на sentinel/missing различия, typed GEOIDs, парсинг summary E/M, отсутствие downscale, duplicate geography/headers, неверную ширину CSV-строк, недостающие колонки, повреждение raw cache, non-food план и запрет получить CDC tracts при запросе только BG. Кроме синтетических проверок, реально проверены все 132 input hashes; повторный offline recovery дал **побайтово идентичные оба gzip-артефакта**. Online normalization пока не проверена на скачанном payload из-за DNS-блокировки, и admission/UI integration не выполнялись.

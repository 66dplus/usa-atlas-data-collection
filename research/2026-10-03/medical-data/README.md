# Медицинские данные: отдельный исследовательский корпус

Сбор выполнен **3 октября 2026 года**. Числа находятся в `normalized/observations.csv` и `normalized/observations.json`, покрытие — в `coverage.json`, определения и наличие по географии — в `metric-inventory.csv` / `.json`. Это отдельный популяционный исследовательский корпус, без изменений БД, каталога показателей, UI или служб.

Для GitHub добавлены компактные детерминированные снимки `normalized/observations.csv.gz` и `child-county/observations.csv.gz`; рядом находятся небольшие CSV наборы дополнительного STI/TB наблюдения и предварительного HIV. Сводка SHA-256 и исходных локальных путей — в `GITHUB-SNAPSHOT.json`. Их можно читать gzip-совместимыми CSV инструментами или распаковать перед использованием путей `.csv` из разделов ниже.

## Сбор: 5 октября 2026

- Добавлен отдельный набор `additional-surveillance/`: **534 числовых наблюдения, 31 показатель** CDC STI/TB. Он не меняет основной и child-county форматы.
- CDC STI 2024 provisional: скачан официальный ZIP с девятью таблицами за 2015–2024. Нормализованы национальные case counts и опубликованные rates по хламидиозу, гонорее и сифилису, включая стадии, sex/partner strata, congenital syphilis и показатель среди женщин 15–44. География только национальная; 2024 provisional as of 2025-08-14. CDC отложил state-level публикацию на время миграции NNDSS. Counts по году рождения congenital syphilis отделены от report-year series; rate denominator для congenital — live births 2023.
- CDC TB reporting-areas HTML и technical notes скачаны напрямую, оба HTTP 200. Добавлены наблюдаемые TB case counts и опубликованные crude rates за 2023 и 2024 для 52 американских reporting areas (49 полных штатов, DC, New York State без NYC и отдельный New York City), национальной строки и восьми территорий/свободно ассоциированных государств. July 1, 2024 population сохранена там, где напечатана; численный знаменатель за 2023 в этой таблице отсутствует. County incidence не предоставлена.
- Проверен CDC HepTracker: официальная страница HTTP 200, публичный Power BI viewer, case data 2024 provisional; в этой сессии нет проверенного machine-readable export, поэтому новые hepatitis числа не добавлялись. AtlasPlus seed 2023 остаётся reportable/acute series, отдельно от chronic prevalence и seroprevalence.
- Живой NCI State Cancer Profiles output=1 запрос к state и county incidence подтвердил HTTP 200 и period 2019–2023. Официальные NCI/CDC methodology, denominator notes, 2026 U.S. Cancer Statistics release notes и public-use data dictionary просмотрены; исходные cancer counts/rates и их county-boundary caveats сохранены.
- На момент этой более ранней записи third bundle включал 88 metric IDs и 98 753 числовые ячейки. Последующие изменения 5 октября учтены ниже; ячейки не являются пациентами или объединённой заболеваемостью.

Детали методики, source receipts, export hashes, точная география и continuation queue: `additional-surveillance/README.md`, `additional-surveillance/source-checks.json`, `source-register.json`, `backlog.json`, `sessions/2026-10-05/SESSION.md`.


## Продолжение сбора: 5 октября 2026 — знаменатели детской смертности

- Добавлен ограниченный collector `collect_child_population_denominators.py` для Census PEP Vintage 2025 `CC-EST2025-SYASEX`: 51 официальный state/DC CSV успешно получен по прямым URL с HTTP 200, размером, временем, параметрами и SHA-256 в `http-receipts.jsonl`. Выход `child-age-bands/census-pep-2025-age1-4-population.csv` содержит 62 880 проверенных записей для 3 144 county-equivalent FIPS, пяти лет 2020–2024 и возрастов 1, 2, 3, 4.
- Создан отдельный показатель `child_mortality_1_4_derived_county_rate`: прямое 2020–2024 число CDC WONDER разделено на сумму 20 годовых July 1 Census PEP оценок населения 1–4 лет и умножено на 100 000. Есть 1 186 числовых rates из 3 142 county source rows; 1 952 остаются null из-за suppression смерти <10, ещё 4 видимые count остаются без знаменателя из-за отсутствия точного FIPS match. 283 числовых ставки помечены ненадёжными по порогу CDC/NCHS <20 смертей. CI не опубликованы и не выводились. Это производная county crude rate с PEP Vintage 2025; она не напрямую сравнима с опубликованными WONDER state rates.
- Сохранены 11 source FIPS, несовместимых с Census Gazetteer 2025, без распределения; 13 reference county-equivalents не имеют точного source FIPS в WONDER файле. Данные Census остаются поддерживающим знаменателем, а не наблюдением смертей или модельной оценкой.
- Повторно открыты официальные WONDER release/help страницы: county infant ID за 2017+ основан на пороге 250 000 жителей по Census 2010; меньшие county входят в `Unidentified Counties`. HIV AtlasPlus показывает семью estimate tables без data vintage на статической странице, а официальный model-release page по-прежнему ссылается на 2018–2022. Новые предварительные диагнозы 2025 и январь–июнь 2026, собранные отдельно в `hiv-preliminary/`, не являются estimated incidence.
- После пересборки core содержит 133 968 строк, включая 93 807 числовых; объединённый индекс — 94 metric IDs и 106 627 числовых ячеек во всех отдельных bundles.

Подробные receipt, coverage и продолжение — `child-age-bands/census-pep-2025-coverage.json`, `coverage-geographies.json`, `source-register.json`, `backlog.json` и [отчёт текущей сессии](sessions/2026-10-05/SESSION.md). Источники: [Census PEP county tables](https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-detail.html), [Census CC-EST2025-SYASEX file layout](https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2020-2025/CC-EST2025-SYASEX.pdf), [CDC WONDER linked infant help](https://wonder.cdc.gov/wonder/help/lbd-expanded.html), [CDC current HIV model release](https://www.cdc.gov/hiv-data/nhss/estimated-hiv-incidence-and-prevalence.html).

## Продолжение сбора: 4 октября 2026

Это продолжение первичного seed, поэтому таблица итогов ниже описывает состояние на конец 3 октября, а не весь текущий корпус.

- CDC WONDER linked-infant county и state выгрузки за **2020–2024** получены с успешными HTTP 200 ответами и нормализованы отдельно как period-linked deaths, live births и rates. Для данных 2017+ видимы только counties, достигавшие 250 000 жителей по переписи 2010 года. Более мелкие округа остаются штатными агрегатами `Unidentified Counties`; значения не распределяются. Данные, знаменатели, 1–9 suppressions и unreliable-rate flags хранятся в `normalized/observations.csv`, покрытия — в `coverage-geographies.json`.
- CDC WONDER теперь содержит county/state **смертность в возрастах 1–4 и 5–14 лет за объединённые 2020–2024 годы**. Counts остаются pooled totals; direct county 1–4 rates/populations не выдаются источником. Для 5–14 отдельно опубликован только явно derived county rate из direct 5–14 count и двух пятилетних возрастных denominators; suppressed cells остаются null.
- Получены county/state cancer mortality выгрузки NCI за **2020–2024** для all sites, lung/bronchus, female breast, colorectal, male prostate и melanoma; отдельные site/population definitions и среднегодовые counts сохранены.
- CDC/NCHHSTP estimated HIV incidence из официального отчёта 2024 года добавлена отдельно от diagnoses: observations за **2022**, state/DC/Puerto Rico и 49 выбранных county/municipality из EHE Phase I, 60 числовых и 41 не показанная CDC ячейка из-за RSE >50%. Числа округлены CDC и модельные; county selection не является полным набором округов. Официальная release-страница всё ещё ссылается на report 2018–2022; текущая статическая страница AtlasPlus показывает категорию estimated incidence/prevalence, но не указывает vintage выгрузки. Модельный vintage нужно сверять по фактической live-таблице.
- В той же официальной CDC-выгрузке отдельно нормализована estimated total HIV prevalence за **2022**: Table 13 — 50 штатов, DC и Puerto Rico; Table A2 — DC и 49 выбранных county/municipality EHE Phase I. Для обеих географий сохранены count и rate, 95% CI, RSE и отмеченные CDC лабораторные/смертностные ограничения. Число людей living with diagnosed or undiagnosed HIV не смешано с observed diagnosed prevalence; для prevalence география — последний известный адрес на конец года. У обеих HIV-модельных series точное число населения-знаменателя не опубликовано в ячейках; сохранены возраст 13+, rate per 100,000 и Census Vintage 2022 denominator source.
- Проверка текущих NCI/CDC cancer releases подтвердила, что скачанные State Cancer Profiles incidence exports относятся к 2019–2023, mortality exports — к 2020–2024. Текущие CDC USCS technical notes (2026) указывают на incidence through 2023 и deaths through 2024; period, source population and average annual count remain distinct in normalized records.

Подробные receipts, hashes и сырые данные находятся в `http-receipts.jsonl`, `source-register.json` и `raw/`; задача и точное продолжение — в `backlog.json` и `sessions/2026-10-04/SESSION.md`.

## Начальный seed: что было собрано к 3 октября 2026

Следующие итоги описывают исходный seed на 3 октября, а не все более поздние пополнения; текущее county/state покрытие см. в записях выше и `coverage.json`.

- **Рак: заболеваемость за 2019–2023** — восемь отдельных county- и state-экспортов NCI/CDC: все локализации, лёгкие, женская грудь, колоректальный рак, мужская простата, меланома, поджелудочная железа, печень и внутрипечёночные желчные протоки.
- **Рак: смертность за 2020–2024** — отдельные county- и state-экспорты всех локализаций NCI, с возрастной стандартизацией и среднегодовым числом смертей. Это доступная альтернативная выгрузка для прежней незаполненной темы Cancer deaths, но пока не импорт в БД.
- **ВИЧ за 2024** — официальный живой table-export API AtlasPlus: новые диагнозы и распространённость диагностированного ВИЧ, отдельно counts/rates и county/state. Три неуспешные части восстановлены 12 запросами по 100 geography IDs. Получены строки для всех 3 144 современных округов и 51 территории; подавленные значения остаются null.
- **Младенческая смертность за 2024** — CDC Stats of the States: 51 территория, число смертей до одного года и показатель на 1 000 живорождений. Числа прочитаны из JSON, который питает официальную визуализацию.
- **Детская смертность 1–4 и 5–14 лет за 2024** — начальные четыре национальных наблюдения CDC/NVSS. Отдельная выгрузка 2020–2024 по штатам и counties добавлена позже; это другие годы и отдельные метрики.
- **Гепатиты за 2023** — опубликованные в живом AtlasPlus state-экспорты: A, острый B, острый C, counts/rates. Они показывают зарегистрированные случаи; нельзя считать их всеми инфекциями или хроническим гепатитом.

Точные числа наблюдений, числовых/подавленных ячеек и географий находятся в `coverage.json`. `county_source_rows` не равно числу современных округов: отдельно показан `county_current_census_numeric` после сверки кодов с **Census Gazetteer 2025**.

## Итог основного seed

**70 744 наблюдения, 58 355 числовых, 12 389 null; 34 показателя с наблюдениями и один HSV-показатель без чисел.** Counts и rates — отдельные metric IDs. National строки не входят в county coverage.

| Показатель | Период | County: числовые исходные / современные Census2025 | State + DC: числовые |
|---|---|---:|---:|
| Рак, все локализации: новые случаи | 2019–2023 | 3 131 / 3 122 | 51 |
| Рак лёгких: новые случаи | 2019–2023 | 2 865 / 2 856 | 51 |
| Рак женской груди: новые случаи | 2019–2023 | 2 881 / 2 872 | 51 |
| Колоректальный рак: новые случаи | 2019–2023 | 2 779 / 2 770 | 51 |
| Рак мужской простаты: новые случаи | 2019–2023 | 2 917 / 2 908 | 51 |
| Меланома: новые случаи | 2019–2023 | 2 361 / 2 353 | 51 |
| Рак поджелудочной железы: новые случаи | 2019–2023 | 2 066 / 2 058 | 51 |
| Печень и внутрипечёночные протоки: новые случаи | 2019–2023 | 1 609 / 1 601 | 51 |
| Рак, все локализации: смерти | 2020–2024 | 3 084 / 3 074 | 51 |
| ВИЧ: новые диагнозы, 13+ | 2024 | 1 978 / 1 978 | 51 |
| Люди с диагностированным ВИЧ, 13+ | 2024 | 2 735 / 2 735 | 51 |
| Младенческая смертность до 1 года | 2024 | Пока не собрана в начальном seed | 51 |
| Детская смертность 1–4 / 5–14 | 2024 | Только национальные 4 наблюдения в начальном seed | 51 в начальном наборе |

NCI incidence содержит по 3 143 target source-county строки каждого типа; mortality — 3 142. Неизвестные / подавленные значения включены в observations как null. ВИЧ: metadata предлагает 3 159 source IDs, API возвращает 3 155; отсутствуют только упразднённые AK `02201`, `02232`, `02280` и VA `51515`. Все 3 144 современные Census2025 FIPS имеют строку. Дополнительные 11 старых FIPS помечены несовместимыми с современной географией. Подробности — `hiv-county-selection-audit.json`; конфликтующих повторных строк нет.

Гепатиты A / острый B / острый C: county не собран; state counts числовые для 51 / 51 / 49 территорий, rates для 50 / 48 / 48. Отсутствующие state ячейки остаются null. `state-coverage.csv` / `.json` описывают каждый показатель по всем 51 территориям.

Отдельный корпус `child-county/` остаётся самостоятелен и не смешивается с прямыми возрастными группами WONDER 1–4 и 5–14. Archived under18 и latest under20 имеют собственные периоды и географии.

## Дополнительный county-набор детской смертности

[Отдельный корпус child-county](child-county/README.md) содержит наблюдаемые NCHS смертности, опубликованные County Health Rankings: **0–17 лет, 2017–2020 — 1 884 округа с числами**; **0–19, 2019–2022 — 2 058**; **0–19, 2020–2023 — 2 041**. В raw дополнительно сохранены state/DC строки; в длинный county-корпус они не включены. Возрастные определения сохранены раздельно. Count — полный четырёхлетний итог смертей; rate — среднегодовой crude показатель на 100 000 населения данного возраста, со знаменателем суммы ежегодных оценок населения. Это не `average_annual_count` NCI и не показатель на 1 000 живорождений.

Объединённый индекс всех показателей — [all-metric-inventory.csv](all-metric-inventory.csv); сводка отдельных корпусов и охвата — [research-overview.json](research-overview.json). Основные `normalized/` и `coverage.json` относятся к core-корпусу, данные помощника — к `child-county/`. Числа ячеек не являются числом пациентов или суммой разных заболеваний.

## Определения

### Рак

Регистровая **incidence** — новые случаи рака; **mortality** — смерти; это не доля взрослых, когда-либо имевших диагноз, и не модельная распространённость PLACES. Коэффициенты NCI стандартизированы к населению США 2000 года и выражены на 100 000 в год за объединённый пятилетний период. Для груди использовано женское население, для простаты — мужское; остальные наборы — оба пола, все расы/этничности, все возрасты.

`average_annual_count` — опубликованное округлённое среднегодовое число. Его нельзя умножать на пять и выдавать результат за точное общее количество. Исходные CI сохранены. `*` — подавленная ячейка; `3 or fewer` — диапазон, не точное число и не ноль. NCI указывает порог менее 16 записей в группе area/sex/race за период. Ненумерические ячейки оставлены null.

### ВИЧ

`hiv_diagnoses` — диагнозы в году, не оценённое число заражений в этом году. `hiv_diagnosed_prevalence` — люди с диагностированным ВИЧ, учитываемые как живущие с ним; не оценка всех инфекций с недиагностированными случаями. Выбраны 13+ лет, оба пола, все расы и категории передачи. Знаменатель населения и код подавления сохранены из API; показатели crude для выбранной возрастной группы, не возрастно стандартизированные.

**Распространённость диагностированного ВИЧ за 2024 имеет оговорку CDC о предварительных данных смертности, полученных до декабря 2025**. Поэтому эти строки помечены `preliminary: true`, даже при завершённой задержке регистрации диагнозов. Предварительные диагнозы 2025 и январь–июнь 2026 собраны отдельно в `hiv-preliminary/`; это диагнозы по дате регистрации, не модельные новые инфекции и не оценка общей распространённости. География распространённости основана на последнем известном адресе; это не всегда место первоначального диагноза.

`AtlasPlus_historic-data-extract_20250430_1.csv` тоже скачан: **237 496 строк, только национальная география US**, преимущественно страты гендерной идентичности. Архив не обновляется; он не удовлетворяет county-цель и не смешан с текущими географическими итогами. В приложении он представлен как исторический доступ к удалённым ранее записям.

### Смертность детей

Infant — смерть до первого дня рождения; показатель на **1 000 живорождений**. Данные State Stats происходят из mortality series CDC WONDER; они не объявлены здесь равными weighted linked birth/infant-death series. Общий текст страницы об age-adjustment не переопределяет специальную единицу infant rate. Точное число живорождений в JSON не приведено и из округлённого rate не восстановлено.

В возрасте **1–4 / 5–14** единица — смерти на **100 000 населения соответствующего возраста**. State rates опубликованы CDC WONDER; county 5–14 rates отдельно выведены из прямого death count и опубликованных групп 5–9/10–14. Для 1–4 county rate отдельно выведен только при точном совпадении FIPS с Census PEP Vintage 2025; он имеет другой источник/vintage знаменателя и не напрямую сравним со state rate. Супрессированные counts и отсутствующий знаменатель дают null; CI не создавались.

## География и приватность

BG и tract не доступны в выбранных общенациональных регистровых bulk-экспортах. County — следующий собранный уровень; state — отдельная fallback-выгрузка, без размножения штата по округам.

NCI использует старые Connecticut counties вместо новых planning regions. В исходниках встречаются старые коды Alaska / South Dakota и объединённый `51917` Bedford City and County. Они сохранены с флагом несовместимости, без автоматического соединения с картой. `geography-mismatches.json` перечисляет такие коды. National и Puerto Rico из US county coverage исключены; источник Puerto Rico остаётся в raw.

Для linked infant-death данных WONDER за 2017+ публично идентифицирует только counties, отвечавшие порогу 250 000 жителей по переписи 2010 года; малые округа остаются state-specific `Unidentified Counties`. Не присваивать агрегат отдельному county. Экспорт county/state за 2020–2024 получен; WONDER подавляет 1–9 событий и помечает rates при менее 20 смертях как ненадёжные. FIPS `12025` сохраняется вместе с официальным источниковым alias к Miami-Dade `12086`; source ID не переписывается.

## Герпес

CDC показывает genital herpes как **не nationally notifiable**. Единой общенациональной таблицы county/state числа диагнозов из этой системы нет. NHANES серопреvalence HSV-1/HSV-2 — отдельная национальная выборочная оценка, с возрастным диапазоном и CI; она не превращается в county-кейсы. Показатель отмечен отсутствующим, без нулевых значений.

## Воспроизведение и продолжение

`collect_medical.py cancer` собирает восемь county/state incidence и all-sites county/state mortality; `mortality-state` — только state mortality; `supporting` — infant JSON, national child-health page и Census county-reference; `hiv` — архив; `atlas-live` — текущие ВИЧ county/state и state-гепатиты. API `/qtOutputData` использует POST как **чтение статистической таблицы**, в формате того же публичного приложения. Запросы разбиты по 400 географий; `atlas-retry` восстановил три неуспешные части партиями по 100 IDs, не перескачивая успешные.

`normalize_medical.py` читает уже сохранённые файлы, сохраняет подавления и сведения о географии. Нормализацию можно повторить после нового скачивания. `collect_child_population_denominators.py --fetch --normalize` получает ограниченные Census PEP CSV и строит компактную таблицу; режим `--normalize` использует уже сохранённые источники. Коллектор не обходит подавления и не запрашивает личные записи.

`audit_medical.py` обновляет requested-versus-returned HIV geography audit, state coverage, source-register и SHA-256 artifact manifest. Он не пересчитывает подавленные значения. Для обновления seed запускать normalizer, затем audit. Child-county helper имеет собственные артефакты и исключён из общего manifest, пока его сессия активна. Страница CDC c устаревшим Socrata COVID-death экспортом заканчивается в 2023 году и **не использована** как state child mortality 2024. Ошибочный metadata CSV URL для infant визуализации также не принят; использован доступный embedded JSON.

Все URL, SHA-256, HTTP status, ETag/Last-Modified при наличии, query-параметры и JSON query payload находятся в `http-receipts.jsonl` и `source-register.json`. Для API нет гарантии неизменного внутреннего порядка полей: проверять его по приложению и контрольному примеру при обновлении. Недельная очередь — `backlog.json` и `WEEKLY-HANDOFF.md`; расписание регистрирует основной агент отдельно.

После изменения любого корпуса обновить сводный индекс: `python3 research/2026-10-03/medical-data/build_overview.py`.
